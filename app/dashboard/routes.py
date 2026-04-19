from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import Category, DashboardUser, Group, Link, Message, Summary, User
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


def _to_bkk(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(_BKK).strftime("%Y-%m-%d %H:%M")


templates.env.filters["to_bkk"] = _to_bkk

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
    resp.set_cookie("session", token, httponly=True, samesite="lax", max_age=60 * 60 * 8)
    return resp


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
    group_id: int | None = None,
    category_id: int | None = None,
    msg_type: str | None = None,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    user: DashboardUser = Depends(get_current_user),
):
    page_size = 50
    query = db.query(Message).order_by(Message.sent_at.desc())
    if q:
        query = query.filter(Message.text.like(f"%{q}%"))
    if group_id:
        query = query.filter(Message.group_id == group_id)
    if category_id:
        query = query.filter(Message.category_id == category_id)
    if msg_type:
        query = query.filter(Message.msg_type == msg_type)

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
            "msg_type": msg_type or "",
            "group_id": group_id, "category_id": category_id,
        },
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


@router.post("/summaries/run")
def summaries_run(
    period: str = Form("daily"),
    ref: str | None = Form(None),
    user: DashboardUser = Depends(get_current_user),
):
    d = date.fromisoformat(ref) if ref else None
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
