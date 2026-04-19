"""Background enrichment — OCR images, extract doc text, fetch link titles, summarize videos, embed."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..database import SessionLocal
from ..models import Link, Message, MessageStandard, Standard
from .doc_extractor import SUPPORTED_EXTS as DOC_EXTS, extract as extract_doc
from .gemini_client import classify_standards, ocr_image
from .link_metadata import fetch_title
from .minio_client import get_object_bytes

log = logging.getLogger(__name__)
settings = get_settings()

_MIME_BY_EXT = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp",
}


async def enrich_message(message_id: int) -> None:
    """Run all enrichment steps for a message.

    Blocking calls (MinIO, Gemini, document parsers) are off-loaded to the
    default thread pool so the event loop stays responsive. DB writes within a
    single step are batched into one commit at the end.
    """
    db = SessionLocal()
    failed = False
    try:
        m: Message | None = (
            db.query(Message)
            .options(selectinload(Message.links))
            .filter(Message.id == message_id)
            .first()
        )
        if not m:
            return
        m.enrich_attempts = (m.enrich_attempts or 0) + 1
        db.commit()

        dirty = False

        # 1. OCR image
        if m.msg_type == "image" and m.media_path and not m.ocr_text:
            ext = m.media_path.rsplit(".", 1)[-1].lower()
            mime = _MIME_BY_EXT.get(ext, "image/jpeg")
            try:
                data = await asyncio.to_thread(get_object_bytes, m.media_path)
                text = await asyncio.to_thread(ocr_image, data, mime)
            except Exception:
                log.exception("OCR failed for message %s", message_id)
                text = None
            if text:
                m.ocr_text = text[: settings.MAX_OCR_TEXT_LEN]
                dirty = True

        # 2. Document text extraction (docx/xlsx/pptx/pdf)
        if m.msg_type == "file" and m.media_path and not m.doc_text:
            ext = m.media_path.rsplit(".", 1)[-1].lower()
            if ext in DOC_EXTS:
                try:
                    data = await asyncio.to_thread(get_object_bytes, m.media_path)
                    text = await asyncio.to_thread(extract_doc, data, ext)
                except Exception:
                    log.exception("doc extract failed for message %s", message_id)
                    text = None
                if text:
                    m.doc_text = text[: settings.MAX_DOC_TEXT_LEN]
                    dirty = True

        # 3. Link titles + YouTube transcript/summary
        for ln in m.links or []:
            if not ln.title:
                try:
                    title = await fetch_title(ln.url, ln.kind)
                except Exception:
                    log.exception("title fetch failed: %s", ln.url)
                    title = None
                if title:
                    ln.title = title
                    dirty = True

            if ln.kind == "youtube" and not ln.summary:
                try:
                    from .youtube_extractor import fetch_transcript_and_summary
                    tr, summary = await asyncio.to_thread(
                        fetch_transcript_and_summary, ln.url
                    )
                except Exception:
                    log.exception("youtube extract failed: %s", ln.url)
                    tr, summary = None, None
                if tr:
                    ln.transcript = tr[: settings.MAX_TRANSCRIPT_LEN]
                    dirty = True
                if summary:
                    ln.summary = summary
                    dirty = True

        if dirty:
            db.commit()

        # 4. Embed for semantic search
        try:
            from .embeddings import embed_message
            await asyncio.to_thread(embed_message, m)
        except Exception:
            log.exception("embed failed for message %s", message_id)

        # 5. Extract entities + decisions + action items
        try:
            from .knowledge_extractor import extract_knowledge
            await asyncio.to_thread(extract_knowledge, message_id)
        except Exception:
            log.exception("knowledge extraction failed for %s", message_id)

        # 6. Classify against SAR standards
        try:
            await asyncio.to_thread(_classify_standards, m.id)
        except Exception:
            log.exception("standard classification failed for %s", message_id)
    except Exception as e:
        failed = True
        log.exception("enrichment fatal for %s", message_id)
        try:
            row = db.get(Message, message_id)
            if row:
                row.enrich_status = "failed"
                row.enrich_error = str(e)[:512]
                db.commit()
        except Exception:
            db.rollback()
    finally:
        if not failed:
            try:
                row = db.get(Message, message_id)
                if row:
                    row.enrich_status = "done"
                    row.enrich_error = None
                    db.commit()
            except Exception:
                db.rollback()
        db.close()


async def retry_failed(limit: int = 50, max_attempts: int = 5) -> int:
    """Re-enqueue enrichment for messages stuck in 'failed' or 'pending'.

    Skips rows that already exceeded max_attempts to avoid infinite loops.
    Returns the number re-processed.
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(Message.id)
            .filter(Message.enrich_status.in_(("failed", "pending")))
            .filter(Message.enrich_attempts < max_attempts)
            .order_by(Message.id.desc())
            .limit(limit)
            .all()
        )
        ids = [r[0] for r in rows]
    finally:
        db.close()
    for mid in ids:
        try:
            await enrich_message(mid)
        except Exception:
            log.exception("retry failed for %s", mid)
    return len(ids)


def _classify_standards(message_id: int) -> None:
    """Auto-tag message with SAR standards based on text/ocr/doc content.

    Opens its own session so it can run from a thread pool.
    """
    db = SessionLocal()
    try:
        msg = db.get(Message, message_id)
        if not msg:
            return
        content = " ".join(s for s in (msg.text, msg.ocr_text, msg.doc_text) if s)
        if len(content.strip()) < 20:
            return
        has_auto = db.query(MessageStandard).filter_by(
            message_id=msg.id, source="auto"
        ).first()
        if has_auto:
            return
        stds = db.query(Standard).filter_by(is_active=1).all()
        catalog = [{"code": s.code, "title": s.title} for s in stds]
        picks = classify_standards(content, catalog)
        if not picks:
            return
        by_code = {s.code: s for s in stds}
        existing = {
            ms.standard_id for ms in db.query(MessageStandard.standard_id)
            .filter_by(message_id=msg.id).all()
        }
        for p in picks:
            std = by_code.get(p["code"])
            if not std or std.id in existing:
                continue
            db.add(MessageStandard(
                message_id=msg.id, standard_id=std.id,
                confidence=p["confidence"], source="auto",
            ))
        db.commit()
    finally:
        db.close()
