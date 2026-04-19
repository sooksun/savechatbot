"""RAG: answer question using top-K relevant messages as context."""
from __future__ import annotations

import logging

from ..database import SessionLocal
from ..models import Group, Message
from .embeddings import search as semantic_search
from .gemini_client import _generate

log = logging.getLogger(__name__)


def _resolve_group_id(line_group_id: str | None) -> int | None:
    if not line_group_id:
        return None
    db = SessionLocal()
    try:
        g = db.query(Group).filter_by(line_group_id=line_group_id).first()
        return g.id if g else None
    finally:
        db.close()


def _build_context(message_ids: list[int]) -> str:
    if not message_ids:
        return ""
    db = SessionLocal()
    try:
        rows = (
            db.query(Message)
            .filter(Message.id.in_(message_ids))
            .order_by(Message.sent_at.asc())
            .all()
        )
        lines: list[str] = []
        for m in rows:
            when = m.sent_at.strftime("%Y-%m-%d %H:%M") if m.sent_at else "?"
            who = m.user.display_name if m.user else "ไม่ทราบ"
            body_parts: list[str] = []
            if m.text:
                body_parts.append(m.text)
            if m.ocr_text:
                body_parts.append(f"(OCR) {m.ocr_text[:1000]}")
            if m.doc_text:
                body_parts.append(f"(เอกสาร) {m.doc_text[:3000]}")
            for ln in m.links or []:
                if ln.summary:
                    body_parts.append(f"(วิดีโอ) {ln.summary[:1500]}")
            body = "\n".join(body_parts).strip() or f"[{m.msg_type}]"
            lines.append(f"[#{m.id} | {when} | {who}]\n{body}")
        return "\n\n---\n\n".join(lines)
    finally:
        db.close()


def answer(question: str, line_group_id: str | None, k: int = 8) -> str:
    gid = _resolve_group_id(line_group_id)
    hits = semantic_search(question, group_id=gid, limit=k)
    ids = [h["message_id"] for h in hits if h.get("message_id")]
    if not ids:
        return "ไม่พบข้อมูลที่เกี่ยวข้องในฐานความรู้ของกลุ่ม"

    context = _build_context(ids)
    prompt = (
        "คุณคือผู้ช่วยตอบคำถามจากบทสนทนาและเอกสารภายในกลุ่ม LINE\n"
        "กติกา:\n"
        "- ตอบเป็นภาษาไทย กระชับ ตรงประเด็น\n"
        "- ใช้ข้อมูลจาก context ด้านล่างเท่านั้น ห้ามเดาเอง\n"
        "- ถ้าข้อมูลไม่พอให้ตอบว่า 'ไม่พบข้อมูลเพียงพอ'\n"
        "- อ้างอิงที่มาเป็นเลขข้อความในวงเล็บเหลี่ยม เช่น [#123] ต่อท้ายประโยคที่ใช้ข้อมูลนั้น\n\n"
        f"คำถาม: {question}\n\n"
        f"Context:\n{context}\n\n"
        "คำตอบ:"
    )
    result = _generate(prompt)
    return result or "ขออภัย ไม่สามารถตอบได้ในขณะนี้"
