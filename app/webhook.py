"""LINE webhook endpoint. Validates signature, persists events."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal
from .models import Category, Group, Link, Message, User
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


async def _handle_event(db: Session, event: dict, background: BackgroundTasks) -> None:
    if event.get("type") != "message":
        return
    msg = event.get("message", {})
    src = event.get("source", {})
    line_mid = msg.get("id")
    if not line_mid:
        return
    if db.query(Message).filter_by(line_message_id=line_mid).first():
        return  # idempotent

    # Command handling (text messages only, starts with '!')
    if msg.get("type") == "text" and is_command(msg.get("text")) and event.get("replyToken"):
        background.add_task(
            handle_command, msg["text"], event["replyToken"], src.get("groupId")
        )
        return

    mtype = msg.get("type", "text")
    group = await _ensure_group(db, src.get("groupId"))
    user = await _ensure_user(db, src.get("userId"), src.get("groupId"))

    text = msg.get("text") if mtype == "text" else None
    media_path: str | None = None
    if mtype in ("image", "video", "audio", "file"):
        ext = {"image": "jpg", "video": "mp4", "audio": "m4a", "file": "bin"}.get(mtype, "bin")
        try:
            media_path = await download_line_content(line_mid, ext=ext)
        except Exception as e:
            log.exception("media download failed: %s", e)

    category_id = _resolve_category(db, text) if text else None

    m = Message(
        line_message_id=line_mid,
        group_id=group.id if group else None,
        user_id=user.id if user else None,
        category_id=category_id,
        msg_type=mtype,
        text=text,
        media_path=media_path,
        sent_at=_ts_to_dt(event.get("timestamp")),
    )
    db.add(m)
    db.flush()

    for ln in extract_links(text):
        db.add(Link(message_id=m.id, url=ln.url, kind=ln.kind))
    db.commit()

    # Offload slow work (OCR, link title fetch) so webhook returns fast.
    needs_enrich = m.msg_type == "image" or bool(m.links) or extract_links(text)
    if needs_enrich:
        background.add_task(enrich_message, m.id)


@router.post("/webhook")
async def webhook(
    request: Request,
    background: BackgroundTasks,
    x_line_signature: str | None = Header(default=None),
):
    body = await request.body()
    if not _verify(body, x_line_signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = await request.json()
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
