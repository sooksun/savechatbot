"""Background enrichment — fetch link titles, OCR images. Called from webhook."""
from __future__ import annotations

import logging
from pathlib import Path

from ..config import get_settings
from ..database import SessionLocal
from ..models import Link, Message
from .gemini_client import ocr_image
from .link_metadata import fetch_title

log = logging.getLogger(__name__)
settings = get_settings()


async def enrich_message(message_id: int) -> None:
    db = SessionLocal()
    try:
        m: Message | None = db.get(Message, message_id)
        if not m:
            return

        if m.msg_type == "image" and m.media_path and not m.ocr_text:
            full = str(Path(settings.MEDIA_ROOT) / m.media_path)
            try:
                text = ocr_image(full)
            except Exception:
                log.exception("OCR failed for message %s", message_id)
                text = None
            if text:
                m.ocr_text = text
                db.commit()

        links = db.query(Link).filter(Link.message_id == message_id, Link.title.is_(None)).all()
        for ln in links:
            try:
                title = await fetch_title(ln.url, ln.kind)
            except Exception:
                log.exception("title fetch failed: %s", ln.url)
                title = None
            if title:
                ln.title = title
                db.commit()
    finally:
        db.close()
