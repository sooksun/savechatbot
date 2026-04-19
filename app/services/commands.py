"""LINE in-chat command handlers. All commands start with '!'."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Awaitable

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Group, Message, MessageStandard, Standard, Summary
from .line_client import reply_message
from .rag import answer as rag_answer
from .summarizer import generate_summary

HELP_TEXT = (
    "คำสั่งที่ใช้ได้:\n"
    "!สรุปวันนี้ — สรุปบทสนทนาวันนี้\n"
    "!สรุปเมื่อวาน — สรุปของเมื่อวาน\n"
    "!สรุปสัปดาห์ — สรุปสัปดาห์ปัจจุบัน\n"
    "!ถาม <คำถาม> — ถาม AI จากความรู้ในกลุ่ม\n"
    "!มฐ — แสดงรายการมาตรฐาน SAR\n"
    "!แท็ก <รหัส> [หมายเหตุ] — ผูกข้อความก่อนหน้ากับมาตรฐาน\n"
    "!help — แสดงคำสั่ง"
)


def is_command(text: str | None) -> bool:
    return bool(text) and text.strip().startswith("!")


def _load_summary(db: Session, line_group_id: str | None, period: str, ref: date) -> str:
    gid = None
    if line_group_id:
        g = db.query(Group).filter_by(line_group_id=line_group_id).first()
        if g:
            gid = g.id
    start = ref if period == "daily" else ref - timedelta(days=ref.weekday())
    s = (
        db.query(Summary)
        .filter_by(group_id=gid, period=period, period_start=start)
        .first()
    )
    return s.content_md if s else ""


async def handle(text: str, reply_token: str, line_group_id: str | None) -> None:
    cmd = text.strip().lower()
    today = date.today()

    async def _send_summary(period: str, ref: date) -> None:
        # (re)generate if missing, then reply
        generate_summary(period, ref)
        db = SessionLocal()
        try:
            content = _load_summary(db, line_group_id, period, ref)
        finally:
            db.close()
        await reply_message(reply_token, content or "ยังไม่มีข้อความในช่วงเวลานี้")

    stripped = text.strip()
    if cmd.startswith("!สรุปวันนี้") or cmd == "!today":
        await _send_summary("daily", today)
    elif cmd.startswith("!สรุปเมื่อวาน") or cmd == "!yesterday":
        await _send_summary("daily", today - timedelta(days=1))
    elif cmd.startswith("!สรุปสัปดาห์") or cmd in ("!week", "!weekly"):
        await _send_summary("weekly", today)
    elif stripped.startswith("!มฐ") or cmd in ("!standards", "!std"):
        await reply_message(reply_token, _list_standards())
    elif stripped.startswith("!แท็ก") or stripped.lower().startswith("!tag"):
        await reply_message(reply_token, _tag_previous(stripped, line_group_id))
    elif stripped.startswith("!ถาม") or stripped.lower().startswith("!ask"):
        # Strip leading command token + optional whitespace
        parts = stripped.split(None, 1)
        q = parts[1].strip() if len(parts) > 1 else ""
        if not q:
            await reply_message(reply_token, "พิมพ์: !ถาม <คำถามของคุณ>")
            return
        result = rag_answer(q, line_group_id)
        # LINE reply limit: 5000 chars
        await reply_message(reply_token, result[:4900])
    else:
        await reply_message(reply_token, HELP_TEXT)


def _list_standards() -> str:
    db = SessionLocal()
    try:
        stds = (
            db.query(Standard)
            .filter_by(is_active=1)
            .order_by(Standard.code)
            .all()
        )
        if not stds:
            return "ยังไม่มีมาตรฐานในระบบ"
        lines = ["มาตรฐานการศึกษา (SAR):"]
        for s in stds:
            prefix = "  " if s.parent_code else ""
            lines.append(f"{prefix}{s.code} — {s.title}")
        lines.append("\nใช้: !แท็ก <รหัส> [หมายเหตุ] เพื่อผูกข้อความก่อนหน้า")
        return "\n".join(lines)
    finally:
        db.close()


def _tag_previous(text: str, line_group_id: str | None) -> str:
    """Parse `!แท็ก <code> [note]` and attach the most recent message in the group."""
    parts = text.split(None, 2)
    if len(parts) < 2:
        return "พิมพ์: !แท็ก <รหัสมาตรฐาน> [หมายเหตุ]\nเช่น !แท็ก 1.1 งานวันวิทย์"
    code = parts[1].strip().lstrip("มฐ.").lstrip("มฐ").strip()
    note = parts[2].strip() if len(parts) > 2 else None

    db = SessionLocal()
    try:
        std = db.query(Standard).filter_by(code=code, is_active=1).first()
        if not std:
            return f"ไม่พบรหัสมาตรฐาน '{code}' — ใช้ !มฐ ดูรายการ"
        if not line_group_id:
            return "คำสั่งนี้ใช้ในกลุ่มเท่านั้น"
        g = db.query(Group).filter_by(line_group_id=line_group_id).first()
        if not g:
            return "ไม่พบกลุ่ม"
        # latest non-command message in this group
        prev = (
            db.query(Message)
            .filter(Message.group_id == g.id)
            .filter(~Message.text.like("!%") | Message.text.is_(None))
            .order_by(Message.sent_at.desc())
            .first()
        )
        if not prev:
            return "ไม่พบข้อความก่อนหน้าในกลุ่มนี้"
        existing = db.query(MessageStandard).filter_by(
            message_id=prev.id, standard_id=std.id
        ).first()
        if existing:
            existing.source = "manual"
            if note:
                existing.note = note
        else:
            db.add(MessageStandard(
                message_id=prev.id, standard_id=std.id,
                confidence=1.0, source="manual", note=note,
            ))
        db.commit()
        return f"✅ ผูกข้อความล่าสุดกับมาตรฐาน {std.code} ({std.title}) แล้ว"
    finally:
        db.close()
