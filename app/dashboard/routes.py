from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, text as sa_text
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..database import get_db
from ..models import (
    ActionItem, Category, DashboardUser, Decision, Entity, EntityMention,
    Group, Link, Message, MessageStandard, MessageTag, Standard, Summary, Tag, User,
)
from ..services.embeddings import search as semantic_search
from ..services.enrichment import retry_failed as retry_failed_enrichment
from ..services.minio_client import get_object_stream, stat_object
from ..services.pdf_export import sar_book_to_pdf, summary_to_pdf
from ..services.summarizer import generate_summary
from .auth import (
    get_current_user,
    hash_password,
    make_session_token,
    require_admin,
    verify_password,
)

settings = get_settings()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_BKK = ZoneInfo(settings.TIMEZONE)
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# Strip MySQL boolean-mode FTS metachars so a single stray char doesn't error the query.
_FTS_UNSAFE_RE = re.compile(r'[+\-><()~*"@]')


def _sanitize_fts(q: str) -> str:
    cleaned = _FTS_UNSAFE_RE.sub(" ", q).strip()
    return cleaned[:200]


def _safe_color(value: str, default: str = "#6366f1") -> str:
    return value if _HEX_COLOR_RE.match(value or "") else default


def _opt_int(value: str | None) -> int | None:
    """HTML <select> posts '' for 'any' — treat empty/invalid as no filter."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_media_path(path: str) -> str:
    # Object keys are stored flat (e.g. "2026/04/foo.jpg"). Reject anything that looks
    # like an attempted traversal or absolute path.
    if not path or ".." in path.split("/") or path.startswith(("/", "\\")) or "\x00" in path:
        raise HTTPException(status_code=400, detail="Invalid path")
    return path


def _to_bkk(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(_BKK).strftime("%Y-%m-%d %H:%M")


def _media_url(path: str | None) -> str:
    if not path:
        return ""
    return f"/file/{path}"


templates.env.filters["to_bkk"] = _to_bkk
templates.env.filters["media_url"] = _media_url

router = APIRouter()


# ─── Auth ────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    return templates.TemplateResponse("login.html", {"request": request, "next": next, "error": ""})


@router.post("/login")
def login(
    response: Response,
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    db: Session = Depends(get_db),
):
    user = db.query(DashboardUser).filter_by(username=username, is_active=1).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "next": next, "error": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"},
            status_code=401,
        )
    token = make_session_token(user.id)
    resp = RedirectResponse(next or "/", status_code=303)
    resp.set_cookie(
        "session", token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=60 * 60 * 8,
    )
    return resp


@router.get("/file/{path:path}")
def get_file(
    path: str,
    user: DashboardUser = Depends(get_current_user),
):
    path = _safe_media_path(path)
    try:
        info = stat_object(path)
        resp = get_object_stream(path)
    except Exception:
        raise HTTPException(status_code=404, detail="File not found")

    def _iter():
        try:
            for chunk in resp.stream(32 * 1024):
                yield chunk
        finally:
            resp.close()
            resp.release_conn()

    headers = {}
    filename = path.rsplit("/", 1)[-1]
    headers["Content-Disposition"] = f'inline; filename="{filename}"'
    return StreamingResponse(
        _iter(),
        media_type=info.content_type or "application/octet-stream",
        headers=headers,
    )


@router.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("session")
    return resp


# ─── Protected pages ─────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    today = date.today()
    since = datetime.combine(today - timedelta(days=6), datetime.min.time())
    total = db.query(func.count(Message.id)).scalar() or 0
    week = db.query(func.count(Message.id)).filter(Message.sent_at >= since).scalar() or 0
    groups = db.query(Group).all()
    categories = (
        db.query(Category.name, func.count(Message.id))
        .outerjoin(Message, Message.category_id == Category.id)
        .group_by(Category.id)
        .all()
    )
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "user": user, "total": total, "week": week,
         "groups": groups, "categories": categories},
    )


@router.get("/messages", response_class=HTMLResponse)
def messages(
    request: Request,
    q: str | None = None,
    group_id: str | None = None,
    category_id: str | None = None,
    tag_id: str | None = None,
    msg_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(None, ge=1, le=200),
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    group_id = _opt_int(group_id)
    category_id = _opt_int(category_id)
    tag_id = _opt_int(tag_id)
    page_size = page_size or settings.DASHBOARD_PAGE_SIZE
    query = (
        db.query(Message)
        .options(selectinload(Message.tags).selectinload(MessageTag.tag))
        .order_by(Message.sent_at.desc())
    )
    if q:
        fts_q = _sanitize_fts(q)
        if fts_q:
            try:
                query = query.filter(
                    sa_text("MATCH(messages.text, messages.ocr_text, messages.doc_text) "
                            "AGAINST (:fts IN BOOLEAN MODE)")
                ).params(fts=fts_q)
            except Exception:
                like = f"%{fts_q}%"
                query = query.filter(or_(
                    Message.text.like(like), Message.ocr_text.like(like), Message.doc_text.like(like)
                ))
    if group_id:
        query = query.filter(Message.group_id == group_id)
    if category_id:
        query = query.filter(Message.category_id == category_id)
    if msg_type:
        query = query.filter(Message.msg_type == msg_type)
    if tag_id:
        query = query.join(MessageTag, MessageTag.message_id == Message.id).filter(MessageTag.tag_id == tag_id)

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return templates.TemplateResponse(
        "messages.html",
        {
            "request": request, "user": user, "rows": rows,
            "q": q or "", "page": page,
            "pages": max(1, (total + page_size - 1) // page_size),
            "groups": db.query(Group).all(),
            "categories": db.query(Category).order_by(Category.name).all(),
            "tags": db.query(Tag).order_by(Tag.name).all(),
            "msg_type": msg_type or "",
            "group_id": group_id, "category_id": category_id, "tag_id": tag_id,
        },
    )


# ─── Semantic search ─────────────────────────────────────────────────────────

@router.get("/search", response_class=HTMLResponse)
def search_page(
    request: Request,
    q: str | None = None,
    group_id: str | None = None,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    group_id = _opt_int(group_id)
    results: list[dict] = []
    messages_by_id: dict[int, Message] = {}
    if q:
        hits = semantic_search(q, group_id=group_id, limit=30)
        ids = [h["message_id"] for h in hits if h.get("message_id")]
        if ids:
            rows = (
                db.query(Message)
                .options(selectinload(Message.tags).selectinload(MessageTag.tag))
                .filter(Message.id.in_(ids))
                .all()
            )
            messages_by_id = {m.id: m for m in rows}
        for h in hits:
            m = messages_by_id.get(h["message_id"])
            if m:
                results.append({"message": m, "score": h["score"]})
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request, "user": user, "q": q or "",
            "results": results, "groups": db.query(Group).all(),
            "group_id": group_id,
        },
    )


# ─── Tags admin ──────────────────────────────────────────────────────────────

@router.get("/tags", response_class=HTMLResponse)
def tags_page(
    request: Request,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    rows = (
        db.query(Tag, func.count(MessageTag.message_id))
        .outerjoin(MessageTag, MessageTag.tag_id == Tag.id)
        .group_by(Tag.id)
        .order_by(Tag.name)
        .all()
    )
    return templates.TemplateResponse("tags.html", {"request": request, "user": user, "rows": rows})


@router.post("/tags/add")
def tags_add(
    name: str = Form(...),
    color: str = Form("#6366f1"),
    db: Session = Depends(get_db),
    admin: DashboardUser = Depends(require_admin),
):
    name = name.strip()
    if name and not db.query(Tag).filter_by(name=name).first():
        db.add(Tag(name=name[:64], color=_safe_color(color)))
        db.commit()
    return RedirectResponse("/tags", status_code=303)


@router.post("/tags/delete")
def tags_delete(
    id: int = Form(...),
    db: Session = Depends(get_db),
    admin: DashboardUser = Depends(require_admin),
):
    t = db.get(Tag, id)
    if t:
        db.delete(t)
        db.commit()
    return RedirectResponse("/tags", status_code=303)


@router.post("/messages/{message_id}/tag")
def message_tag_attach(
    message_id: int,
    tag_id: int = Form(...),
    db: Session = Depends(get_db),
    admin: DashboardUser = Depends(require_admin),
):
    if not db.query(MessageTag).filter_by(message_id=message_id, tag_id=tag_id).first():
        db.add(MessageTag(message_id=message_id, tag_id=tag_id))
        db.commit()
    return RedirectResponse("/messages", status_code=303)


@router.post("/messages/{message_id}/untag")
def message_tag_detach(
    message_id: int,
    tag_id: int = Form(...),
    db: Session = Depends(get_db),
    admin: DashboardUser = Depends(require_admin),
):
    mt = db.query(MessageTag).filter_by(message_id=message_id, tag_id=tag_id).first()
    if mt:
        db.delete(mt)
        db.commit()
    return RedirectResponse("/messages", status_code=303)


# ─── Knowledge: entities / decisions / actions / wiki ────────────────────────

@router.get("/entities", response_class=HTMLResponse)
def entities_page(
    request: Request,
    kind: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    query = db.query(Entity).order_by(Entity.mention_count.desc())
    if kind:
        query = query.filter(Entity.kind == kind)
    if q:
        query = query.filter(Entity.name.like(f"%{q}%"))
    rows = query.limit(500).all()
    return templates.TemplateResponse(
        "entities.html",
        {"request": request, "user": user, "rows": rows, "kind": kind or "", "q": q or ""},
    )


@router.get("/entities/{entity_id}", response_class=HTMLResponse)
def entity_detail(
    entity_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    e = db.get(Entity, entity_id)
    if not e:
        raise HTTPException(status_code=404, detail="Entity not found")
    mentions = (
        db.query(Message)
        .join(EntityMention, EntityMention.message_id == Message.id)
        .filter(EntityMention.entity_id == entity_id)
        .order_by(Message.sent_at.desc())
        .limit(200)
        .all()
    )
    return templates.TemplateResponse(
        "entity_detail.html",
        {"request": request, "user": user, "entity": e, "mentions": mentions},
    )


@router.get("/decisions", response_class=HTMLResponse)
def decisions_page(
    request: Request,
    group_id: str | None = None,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    group_id = _opt_int(group_id)
    query = db.query(Decision).order_by(Decision.decided_at.desc())
    if group_id:
        query = query.filter(Decision.group_id == group_id)
    rows = query.limit(300).all()
    return templates.TemplateResponse(
        "decisions.html",
        {"request": request, "user": user, "rows": rows,
         "groups": db.query(Group).all(), "group_id": group_id},
    )


@router.get("/actions", response_class=HTMLResponse)
def actions_page(
    request: Request,
    status: str | None = None,
    group_id: str | None = None,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    group_id = _opt_int(group_id)
    query = db.query(ActionItem).order_by(
        ActionItem.status.asc(), ActionItem.due_date.asc().nulls_last(), ActionItem.created_at.desc()
    )
    if status:
        query = query.filter(ActionItem.status == status)
    if group_id:
        query = query.filter(ActionItem.group_id == group_id)
    rows = query.limit(500).all()
    return templates.TemplateResponse(
        "actions.html",
        {"request": request, "user": user, "rows": rows,
         "groups": db.query(Group).all(),
         "status": status or "", "group_id": group_id},
    )


@router.post("/actions/{action_id}/status")
def action_update_status(
    action_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
    admin: DashboardUser = Depends(require_admin),
):
    a = db.get(ActionItem, action_id)
    if a and status in ("open", "done", "cancelled"):
        a.status = status
        db.commit()
    return RedirectResponse("/actions", status_code=303)


@router.get("/wiki", response_class=HTMLResponse)
def wiki_index(
    request: Request,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    topics = (
        db.query(Entity)
        .filter(Entity.kind == "topic")
        .order_by(Entity.mention_count.desc())
        .limit(100)
        .all()
    )
    people = (
        db.query(Entity)
        .filter(Entity.kind == "person")
        .order_by(Entity.mention_count.desc())
        .limit(50)
        .all()
    )
    orgs = (
        db.query(Entity)
        .filter(Entity.kind == "org")
        .order_by(Entity.mention_count.desc())
        .limit(50)
        .all()
    )
    return templates.TemplateResponse(
        "wiki.html",
        {"request": request, "user": user, "topics": topics, "people": people, "orgs": orgs},
    )


# ─── PDF export ──────────────────────────────────────────────────────────────

@router.get("/summaries/{summary_id}/pdf")
def summary_pdf(
    summary_id: int,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    s = db.get(Summary, summary_id)
    if not s:
        raise HTTPException(status_code=404, detail="Summary not found")
    group_name = "ทุกกลุ่ม"
    if s.group_id:
        g = db.get(Group, s.group_id)
        group_name = (g.name if g and g.name else f"group#{s.group_id}")
    pdf_bytes = summary_to_pdf(
        title=f"สรุป {s.period} {s.period_start} – {s.period_end}",
        group_name=group_name,
        content_md=s.content_md,
    )
    filename = f"summary-{s.period}-{s.period_start}.pdf"
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/links", response_class=HTMLResponse)
def links(
    request: Request,
    kind: str | None = None,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    q = db.query(Link).join(Message).order_by(Message.sent_at.desc())
    if kind:
        q = q.filter(Link.kind == kind)
    return templates.TemplateResponse(
        "links.html",
        {"request": request, "user": user, "rows": q.limit(500).all(), "kind": kind or ""},
    )


@router.get("/summaries", response_class=HTMLResponse)
def summaries(
    request: Request,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    rows = db.query(Summary).order_by(Summary.period_start.desc(), Summary.id.desc()).limit(200).all()
    return templates.TemplateResponse("summaries.html", {"request": request, "user": user, "rows": rows})


@router.post("/enrichment/retry")
async def enrichment_retry(
    limit: int = Form(50),
    admin: DashboardUser = Depends(require_admin),
):
    limit = max(1, min(limit, 500))
    processed = await retry_failed_enrichment(limit=limit)
    return {"processed": processed}


@router.post("/summaries/run")
def summaries_run(
    period: str = Form("daily"),
    ref: str | None = Form(None),
    admin: DashboardUser = Depends(require_admin),
):
    if period not in ("daily", "weekly"):
        raise HTTPException(status_code=400, detail="Invalid period")
    try:
        d = date.fromisoformat(ref) if ref else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date")
    generate_summary(period, d)
    return RedirectResponse("/summaries", status_code=303)


@router.get("/categories", response_class=HTMLResponse)
def categories(
    request: Request,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    rows = db.query(Category).order_by(Category.name).all()
    return templates.TemplateResponse("categories.html", {"request": request, "user": user, "rows": rows})


@router.post("/categories/add")
def categories_add(
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
):
    if name.strip() and not db.query(Category).filter_by(name=name.strip()).first():
        db.add(Category(name=name.strip()[:128], description=description.strip() or None, is_auto=0))
        db.commit()
    return RedirectResponse("/categories", status_code=303)


@router.post("/categories/delete")
def categories_delete(
    id: int = Form(...),
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(require_admin),
):
    c = db.get(Category, id)
    if c:
        db.query(Message).filter(Message.category_id == id).update({"category_id": None})
        db.delete(c)
        db.commit()
    return RedirectResponse("/categories", status_code=303)


# ─── SAR / Standards (Phase 5) ───────────────────────────────────────────────

def _build_evidences(db: Session, std_id: int, limit: int = 500) -> list[dict]:
    """Gather evidence entries linked to a standard, with embeddable image URIs."""
    from ..services.pdf_export import _media_to_data_uri  # local import to avoid cycle
    rows = (
        db.query(Message, MessageStandard)
        .join(MessageStandard, MessageStandard.message_id == Message.id)
        .filter(MessageStandard.standard_id == std_id)
        .order_by(Message.sent_at.desc())
        .limit(limit)
        .all()
    )
    out: list[dict] = []
    for m, ms in rows:
        item: dict = {
            "caption": ms.note or (m.text or "")[:160] or "(ไม่มีคำอธิบาย)",
            "sent_at": m.sent_at,
            "source": ms.source,
        }
        if m.msg_type == "image" and m.media_path:
            uri = _media_to_data_uri(m.media_path)
            if uri:
                item["thumb_uri"] = uri
            else:
                item["text"] = m.ocr_text or m.text or ""
        elif m.msg_type in ("text", "sticker"):
            item["text"] = m.text or ""
        elif m.msg_type == "file":
            item["text"] = f"[{m.original_filename or m.media_path or 'ไฟล์'}] {(m.doc_text or '')[:400]}"
        else:
            links = db.query(Link).filter(Link.message_id == m.id).all()
            if links:
                for ln in links:
                    item_ = dict(item)
                    item_["link_url"] = ln.url
                    item_["link_title"] = ln.title or ""
                    out.append(item_)
                continue
            item["text"] = m.text or ""
        out.append(item)
    return out


@router.get("/standards", response_class=HTMLResponse)
def standards_page(
    request: Request,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    rows = (
        db.query(Standard, func.count(MessageStandard.message_id))
        .outerjoin(MessageStandard, MessageStandard.standard_id == Standard.id)
        .group_by(Standard.id)
        .order_by(Standard.code)
        .all()
    )
    return templates.TemplateResponse(
        "standards.html",
        {"request": request, "user": user, "rows": rows},
    )


@router.post("/standards/add")
def standards_add(
    code: str = Form(...),
    title: str = Form(...),
    parent_code: str = Form(""),
    description: str = Form(""),
    db: Session = Depends(get_db),
    admin: DashboardUser = Depends(require_admin),
):
    code = code.strip()
    if code and not db.query(Standard).filter_by(code=code).first():
        db.add(Standard(
            code=code[:32], title=title.strip()[:255],
            parent_code=parent_code.strip()[:32] or None,
            description=description.strip() or None,
            is_active=1,
        ))
        db.commit()
    return RedirectResponse("/standards", status_code=303)


@router.post("/standards/toggle")
def standards_toggle(
    id: int = Form(...),
    db: Session = Depends(get_db),
    admin: DashboardUser = Depends(require_admin),
):
    s = db.get(Standard, id)
    if s:
        s.is_active = 0 if s.is_active else 1
        db.commit()
    return RedirectResponse("/standards", status_code=303)


@router.get("/standards/{code}", response_class=HTMLResponse)
def standard_detail(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    std = db.query(Standard).filter_by(code=code).first()
    if not std:
        raise HTTPException(status_code=404, detail="Standard not found")
    rows = (
        db.query(Message, MessageStandard)
        .join(MessageStandard, MessageStandard.message_id == Message.id)
        .filter(MessageStandard.standard_id == std.id)
        .order_by(Message.sent_at.desc())
        .limit(300)
        .all()
    )
    return templates.TemplateResponse(
        "standard_detail.html",
        {"request": request, "user": user, "std": std, "rows": rows},
    )


@router.post("/standards/{code}/attach")
def standards_attach(
    code: str,
    message_id: int = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    std = db.query(Standard).filter_by(code=code).first()
    if not std:
        raise HTTPException(status_code=404, detail="Standard not found")
    existing = db.query(MessageStandard).filter_by(
        message_id=message_id, standard_id=std.id
    ).first()
    if existing:
        existing.source = "manual"
        if note.strip():
            existing.note = note.strip()[:512]
    else:
        db.add(MessageStandard(
            message_id=message_id, standard_id=std.id,
            confidence=1.0, source="manual",
            note=note.strip()[:512] or None,
        ))
    db.commit()
    return RedirectResponse(f"/standards/{code}", status_code=303)


@router.post("/standards/{code}/detach")
def standards_detach(
    code: str,
    message_id: int = Form(...),
    db: Session = Depends(get_db),
    admin: DashboardUser = Depends(require_admin),
):
    std = db.query(Standard).filter_by(code=code).first()
    if std:
        db.query(MessageStandard).filter_by(
            message_id=message_id, standard_id=std.id
        ).delete()
        db.commit()
    return RedirectResponse(f"/standards/{code}", status_code=303)


@router.get("/standards/{code}/export.pdf")
def standard_export_pdf(
    code: str,
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    std = db.query(Standard).filter_by(code=code).first()
    if not std:
        raise HTTPException(status_code=404, detail="Standard not found")
    evidences = _build_evidences(db, std.id)
    pdf = sar_book_to_pdf(
        title=f"หลักฐาน SAR มาตรฐานที่ {std.code}",
        year=std.academic_year or "",
        sections=[{
            "code": std.code, "title": std.title,
            "description": std.description or "",
            "evidences": evidences,
        }],
    )
    return Response(
        pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="sar-{std.code}.pdf"'},
    )


@router.get("/sar/export.pdf")
def sar_export_pdf(
    year: str = Query("", description="ปีการศึกษา เช่น 2568", max_length=10, pattern=r"^[0-9]{0,4}$"),
    db: Session = Depends(get_db),
    admin: DashboardUser = Depends(require_admin),
):
    stds = (
        db.query(Standard)
        .filter_by(is_active=1)
        .order_by(Standard.code)
        .all()
    )
    sections = []
    for s in stds:
        sections.append({
            "code": s.code, "title": s.title,
            "description": s.description or "",
            "evidences": _build_evidences(db, s.id),
        })
    pdf = sar_book_to_pdf(title="รายงานการประเมินตนเอง (SAR)", year=year or "-", sections=sections)
    fname = f"sar-{year or 'all'}.pdf"
    return Response(
        pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ─── User management (admin only) ────────────────────────────────────────────

@router.get("/users", response_class=HTMLResponse)
def users_page(
    request: Request,
    db: Session = Depends(get_db),
    admin: DashboardUser = Depends(require_admin),
):
    rows = db.query(DashboardUser).order_by(DashboardUser.id).all()
    return templates.TemplateResponse("users.html", {"request": request, "user": admin, "rows": rows})


@router.post("/users/add")
def users_add(
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("viewer"),
    db: Session = Depends(get_db),
    admin: DashboardUser = Depends(require_admin),
):
    if username.strip() and not db.query(DashboardUser).filter_by(username=username.strip()).first():
        db.add(DashboardUser(
            username=username.strip(),
            password_hash=hash_password(password),
            role=role if role in ("admin", "viewer") else "viewer",
        ))
        db.commit()
    return RedirectResponse("/users", status_code=303)


@router.post("/users/toggle")
def users_toggle(
    id: int = Form(...),
    db: Session = Depends(get_db),
    admin: DashboardUser = Depends(require_admin),
):
    u = db.get(DashboardUser, id)
    if u and u.id != admin.id:  # can't disable yourself
        u.is_active = 0 if u.is_active else 1
        db.commit()
    return RedirectResponse("/users", status_code=303)


@router.post("/users/reset-password")
def users_reset_pw(
    id: int = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    admin: DashboardUser = Depends(require_admin),
):
    u = db.get(DashboardUser, id)
    if u and new_password.strip():
        u.password_hash = hash_password(new_password.strip())
        db.commit()
    return RedirectResponse("/users", status_code=303)


@router.post("/users/delete")
def users_delete(
    id: int = Form(...),
    db: Session = Depends(get_db),
    admin: DashboardUser = Depends(require_admin),
):
    u = db.get(DashboardUser, id)
    if u and u.id != admin.id:
        db.delete(u)
        db.commit()
    return RedirectResponse("/users", status_code=303)
