"""Background enrichment — OCR images, extract doc text, fetch link titles, summarize videos, embed."""
from __future__ import annotations

import logging

from ..config import get_settings
from ..database import SessionLocal
from ..models import Link, Message
from .doc_extractor import SUPPORTED_EXTS as DOC_EXTS, extract as extract_doc
from .gemini_client import ocr_image
from .link_metadata import fetch_title
from .minio_client import get_object_bytes

log = logging.getLogger(__name__)
settings = get_settings()

_MIME_BY_EXT = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp",
}


async def enrich_message(message_id: int) -> None:
    db = SessionLocal()
    try:
        m: Message | None = db.get(Message, message_id)
        if not m:
            return

        # 1. OCR image
        if m.msg_type == "image" and m.media_path and not m.ocr_text:
            ext = m.media_path.rsplit(".", 1)[-1].lower()
            mime = _MIME_BY_EXT.get(ext, "image/jpeg")
            try:
                data = get_object_bytes(m.media_path)
                text = ocr_image(data, mime_type=mime)
            except Exception:
                log.exception("OCR failed for message %s", message_id)
                text = None
            if text:
                m.ocr_text = text
                db.commit()

        # 2. Document text extraction (docx/xlsx/pptx/pdf)
        if m.msg_type == "file" and m.media_path and not m.doc_text:
            ext = m.media_path.rsplit(".", 1)[-1].lower()
            if ext in DOC_EXTS:
                try:
                    data = get_object_bytes(m.media_path)
                    text = extract_doc(data, ext)
                except Exception:
                    log.exception("doc extract failed for message %s", message_id)
                    text = None
                if text:
                    m.doc_text = text[:200_000]  # cap to 200k chars
                    db.commit()

        # 3. Link titles + YouTube transcript/summary
        links = db.query(Link).filter(Link.message_id == message_id).all()
        for ln in links:
            if not ln.title:
                try:
                    title = await fetch_title(ln.url, ln.kind)
                except Exception:
                    log.exception("title fetch failed: %s", ln.url)
                    title = None
                if title:
                    ln.title = title
                    db.commit()

            # YouTube: pull transcript + summary (Phase 3b)
            if ln.kind == "youtube" and not ln.summary:
                try:
                    from .youtube_extractor import fetch_transcript_and_summary
                    tr, summary = fetch_transcript_and_summary(ln.url)
                except Exception:
                    log.exception("youtube extract failed: %s", ln.url)
                    tr, summary = None, None
                if tr:
                    ln.transcript = tr[:200_000]
                if summary:
                    ln.summary = summary
                if tr or summary:
                    db.commit()

        # 4. Embed for semantic search (Phase 3c)
        try:
            from .embeddings import embed_message
            embed_message(m)
        except Exception:
            log.exception("embed failed for message %s", message_id)

        # 5. Extract entities + decisions + action items (Phase 4)
        try:
            from .knowledge_extractor import extract_knowledge
            extract_knowledge(message_id)
        except Exception:
            log.exception("knowledge extraction failed for %s", message_id)
    finally:
        db.close()
