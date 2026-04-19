"""Extract entities, decisions, action items from message text using Gemini structured JSON."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

from ..database import SessionLocal
from ..models import ActionItem, Decision, Entity, EntityMention, Message
from .gemini_client import _generate

log = logging.getLogger(__name__)

_PROMPT = """คุณคือระบบสกัดข้อมูลเชิงความรู้จากบทสนทนา
อ่านข้อความต่อไปนี้แล้วสกัดข้อมูลเป็น JSON ตาม schema ด้านล่าง

ข้อความ:
\"\"\"{body}\"\"\"

schema:
{{
  "entities": [
    {{"kind": "person|org|place|date|topic|money|other", "name": "ชื่อเต็ม"}}
  ],
  "decisions": [
    {{"summary": "สรุปการตัดสินใจ 1 ประโยค"}}
  ],
  "actions": [
    {{"task": "งานที่ต้องทำ", "assignee": "ผู้รับผิดชอบ หรือ null", "due_date": "YYYY-MM-DD หรือ null"}}
  ]
}}

กติกา:
- ถ้าไม่มีในข้อความ ให้ใส่ array ว่าง
- ไม่ต้องแต่งเติม ไม่ต้องเดา
- ตอบเป็น JSON อย่างเดียว
"""


def _norm(s: str) -> str:
    return " ".join(s.lower().split())[:255]


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _message_body(m: Message) -> str:
    parts: list[str] = []
    if m.text:
        parts.append(m.text)
    if m.ocr_text:
        parts.append(f"(OCR) {m.ocr_text[:2000]}")
    if m.doc_text:
        parts.append(f"(เอกสาร) {m.doc_text[:5000]}")
    for ln in m.links or []:
        if ln.summary:
            parts.append(f"(สรุปวิดีโอ) {ln.summary[:2000]}")
    return "\n\n".join(parts).strip()


def extract_knowledge(message_id: int) -> None:
    db = SessionLocal()
    try:
        m = db.get(Message, message_id)
        if not m:
            return
        body = _message_body(m)
        if not body or len(body) < 10:
            return

        raw = _generate(_PROMPT.format(body=body[:8000]), response_mime_type="application/json")
        if not raw:
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("knowledge JSON parse failed for msg %s", message_id)
            return

        # Entities
        for ent in data.get("entities", []) or []:
            kind = (ent.get("kind") or "other").strip().lower()[:32]
            name = (ent.get("name") or "").strip()[:255]
            if not name:
                continue
            normalized = _norm(name)
            existing = db.query(Entity).filter_by(kind=kind, normalized=normalized).first()
            if existing:
                existing.mention_count += 1
                ent_id = existing.id
            else:
                e = Entity(kind=kind, name=name, normalized=normalized, mention_count=1)
                db.add(e)
                db.flush()
                ent_id = e.id
            if not db.query(EntityMention).filter_by(entity_id=ent_id, message_id=m.id).first():
                db.add(EntityMention(entity_id=ent_id, message_id=m.id))

        # Decisions
        for d in data.get("decisions", []) or []:
            summary = (d.get("summary") or "").strip()[:512]
            if not summary:
                continue
            if not db.query(Decision).filter_by(message_id=m.id, summary=summary).first():
                db.add(Decision(
                    message_id=m.id, group_id=m.group_id,
                    summary=summary, decided_at=m.sent_at or datetime.utcnow(),
                ))

        # Action items
        for a in data.get("actions", []) or []:
            task = (a.get("task") or "").strip()[:512]
            if not task:
                continue
            assignee = (a.get("assignee") or None)
            if assignee:
                assignee = assignee.strip()[:128] or None
            due = _parse_date(a.get("due_date"))
            if not db.query(ActionItem).filter_by(message_id=m.id, task=task).first():
                db.add(ActionItem(
                    message_id=m.id, group_id=m.group_id,
                    task=task, assignee=assignee, due_date=due,
                ))

        db.commit()
    except Exception:
        log.exception("knowledge extraction failed for msg %s", message_id)
        db.rollback()
    finally:
        db.close()
