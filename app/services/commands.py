"""LINE in-chat command handlers. All commands start with '!'."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Awaitable

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Group, Summary
from .line_client import reply_message
from .summarizer import generate_summary

HELP_TEXT = (
    "คำสั่งที่ใช้ได้:\n"
    "!สรุปวันนี้ — สรุปบทสนทนาวันนี้\n"
    "!สรุปเมื่อวาน — สรุปของเมื่อวาน\n"
    "!สรุปสัปดาห์ — สรุปสัปดาห์ปัจจุบัน\n"
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

    if cmd.startswith("!สรุปวันนี้") or cmd == "!today":
        await _send_summary("daily", today)
    elif cmd.startswith("!สรุปเมื่อวาน") or cmd == "!yesterday":
        await _send_summary("daily", today - timedelta(days=1))
    elif cmd.startswith("!สรุปสัปดาห์") or cmd in ("!week", "!weekly"):
        await _send_summary("weekly", today)
    else:
        await reply_message(reply_token, HELP_TEXT)
