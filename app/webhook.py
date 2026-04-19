"""LINE webhook endpoint. Validates signature, persists events."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal
from .models import Category, Group, GroupMember, Link, Message, User, WebhookRawEvent
from .services.commands import handle as handle_command, is_command
from .services.enrichment import enrich_message
from .services.gemini_client import classify_message
from .services.line_client import get_group_summary, get_profile
from .services.link_extractor import extract as extract_links
from .services.media_storage import download_line_content

log = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()


def _verify(body: bytes, signature: str | None) -> bool:
    if not signature or not settings.LINE_CHANNEL_SECRET:
        return False
    mac = hmac.new(
        settings.LINE_CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256
    ).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def _ts_to_dt(ms: int | None) -> datetime:
    if not ms:
        return datetime.utcnow()
    return datetime.utcfromtimestamp(ms / 1000.0)


def _save_raw_event(db: Session, event: dict) -> WebhookRawEvent:
    src = event.get("source", {})
    raw = WebhookRawEvent(
        event_type=event.get("type", "unknown"),
        source_type=src.get("type"),
        line_group_id=src.get("groupId"),
        line_user_id=src.get("userId"),
        webhook_event_id=event.get("webhookEventId"),
        payload=json.dumps(event, ensure_ascii=False),
    )
    db.add(raw)
    db.flush()
    return raw


async def _ensure_group(db: Session, line_group_id: str | None) -> Group | None:
    if not line_group_id:
        return None
    g = db.query(Group).filter_by(line_group_id=line_group_id).first()
    if g:
        return g
    info = await get_group_summary(line_group_id)
    g = Group(line_group_id=line_group_id, name=info.get("groupName"))
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


async def _ensure_user(db: Session, line_user_id: str | None, line_group_id: str | None) -> User | None:
    if not line_user_id:
        return None
    u = db.query(User).filter_by(line_user_id=line_user_id).first()
    if u:
        return u
    info = await get_profile(line_user_id, line_group_id)
    u = User(
        line_user_id=line_user_id,
        display_name=info.get("displayName"),
        picture_url=info.get("pictureUrl"),
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _upsert_member(db: Session, group: Group, user: User, active: bool) -> None:
    from sqlalchemy.dialects.mysql import insert as mysql_insert
    m = (
        db.query(GroupMember)
        .filter_by(group_id=group.id, user_id=user.id)
        .first()
    )
    if m:
        m.is_active = active
        if not active:
            m.left_at = datetime.utcnow()
    else:
        m = GroupMember(group_id=group.id, user_id=user.id, is_active=active)
        db.add(m)
    db.flush()


def _resolve_category(db: Session, text: str | None) -> int | None:
    if not text:
        return None
    cats = db.query(Category).all()
    names = [c.name for c in cats]
    picked = classify_message(text, names)
    if not picked:
        return None
    existing = next((c for c in cats if c.name == picked), None)
    if existing:
        return existing.id
    new_cat = Category(name=picked[:128], is_auto=1)
    db.add(new_cat)
    db.commit()
    db.refresh(new_cat)
    return new_cat.id


async def _handle_join(db: Session, event: dict, raw: WebhookRawEvent) -> None:
    src = event.get("source", {})
    line_group_id = src.get("groupId")
    if not line_group_id:
        return
    g = db.query(Group).filter_by(line_group_id=line_group_id).first()
    if not g:
        info = await get_group_summary(line_group_id)
        g = Group(line_group_id=line_group_id, name=info.get("groupName"))
        db.add(g)
        db.commit()
        log.info("Joined new group: %s (%s)", g.name, line_group_id)


async def _handle_leave(db: Session, event: dict, raw: WebhookRawEvent) -> None:
    src = event.get("source", {})
    line_group_id = src.get("groupId")
    if not line_group_id:
        return
    g = db.query(Group).filter_by(line_group_id=line_group_id).first()
    if g:
        log.info("Bot left group: %s", line_group_id)


async def _handle_member_joined(db: Session, event: dict, raw: WebhookRawEvent) -> None:
    src = event.get("source", {})
    line_group_id = src.get("groupId")
    joined_members = event.get("joined", {}).get("members", [])
    if not line_group_id or not joined_members:
        return
    g = await _ensure_group(db, line_group_id)
    if not g:
        return
    for member in joined_members:
        if member.get("type") != "user":
            continue
        user = await _ensure_user(db, member.get("userId"), line_group_id)
        if user:
            _upsert_member(db, g, user, active=True)
    db.commit()


async def _handle_member_left(db: Session, event: dict, raw: WebhookRawEvent) -> None:
    src = event.get("source", {})
    line_group_id = src.get("groupId")
    left_members = event.get("left", {}).get("members", [])
    if not line_group_id or not left_members:
        return
    g = db.query(Group).filter_by(line_group_id=line_group_id).first()
    if not g:
        return
    for member in left_members:
        if member.get("type") != "user":
            continue
        user = db.query(User).filter_by(line_user_id=member.get("userId")).first()
        if user:
            _upsert_member(db, g, user, active=False)
    db.commit()


async def _handle_unsend(db: Session, event: dict, raw: WebhookRawEvent) -> None:
    unsend = event.get("unsend", {})
    line_mid = unsend.get("messageId")
    if not line_mid:
        return
    msg = db.query(Message).filter_by(line_message_id=str(line_mid)).first()
    if msg:
        msg.is_unsent = True
        msg.unsent_at = _ts_to_dt(event.get("timestamp"))
        db.commit()
        log.info("Marked message %s as unsent", line_mid)


async def _handle_message(db: Session, event: dict, raw: WebhookRawEvent, background: BackgroundTasks) -> None:
    msg = event.get("message", {})
    src = event.get("source", {})
    line_mid = msg.get("id")
    if not line_mid:
        return
    if db.query(Message).filter_by(line_message_id=line_mid).first():
        return  # idempotent

    if msg.get("type") == "text" and is_command(msg.get("text")) and event.get("replyToken"):
        background.add_task(
            handle_command, msg["text"], event["replyToken"], src.get("groupId")
        )
        return

    mtype = msg.get("type", "text")
    group = await _ensure_group(db, src.get("groupId"))
    user = await _ensure_user(db, src.get("userId"), src.get("groupId"))

    # Track member activity
    if group and user:
        _upsert_member(db, group, user, active=True)

    text = msg.get("text") if mtype == "text" else None
    media_path: str | None = None
    original_filename: str | None = None
    if mtype in ("image", "video", "audio", "file"):
        fallback = {"image": "jpg", "video": "mp4", "audio": "m4a", "file": "bin"}.get(mtype, "bin")
        try:
            result = await download_line_content(line_mid, fallback_ext=fallback)
            media_path = result.relative_path
            original_filename = result.original_filename
        except Exception as e:
            log.exception("media download failed: %s", e)

    category_id = _resolve_category(db, text) if text else None

    m = Message(
        line_message_id=line_mid,
        group_id=group.id if group else None,
        user_id=user.id if user else None,
        category_id=category_id,
        webhook_event_id=raw.id,
        msg_type=mtype,
        text=text,
        media_path=media_path,
        original_filename=original_filename,
        sent_at=_ts_to_dt(event.get("timestamp")),
    )
    db.add(m)
    try:
        db.flush()
    except IntegrityError:
        # Concurrent webhook delivered the same event — unique constraint on
        # line_message_id rejected us. Treat as duplicate and move on.
        db.rollback()
        return

    extracted_links = list(extract_links(text))
    for ln in extracted_links:
        db.add(Link(message_id=m.id, url=ln.url, kind=ln.kind))
    db.commit()

    needs_enrich = bool(
        m.msg_type in ("image", "file")
        or extracted_links
        or text
    )
    if needs_enrich:
        background.add_task(enrich_message, m.id)


async def _handle_event(db: Session, event: dict, background: BackgroundTasks) -> None:
    raw = _save_raw_event(db, event)
    etype = event.get("type")
    if etype == "join":
        await _handle_join(db, event, raw)
    elif etype == "leave":
        await _handle_leave(db, event, raw)
    elif etype == "memberJoined":
        await _handle_member_joined(db, event, raw)
    elif etype == "memberLeft":
        await _handle_member_left(db, event, raw)
    elif etype == "unsend":
        await _handle_unsend(db, event, raw)
    elif etype == "message":
        await _handle_message(db, event, raw, background)


@router.post("/webhook")
async def webhook(
    request: Request,
    background: BackgroundTasks,
    x_line_signature: str | None = Header(default=None),
):
    try:
        body = await request.body()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")
    if not _verify(body, x_line_signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    events = payload.get("events", [])
    db: Session = SessionLocal()
    try:
        for ev in events:
            try:
                await _handle_event(db, ev, background)
            except Exception:
                log.exception("event handling failed")
                db.rollback()
    finally:
        db.close()
    return {"ok": True}
