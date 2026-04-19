from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import SessionLocal
from ..models import Group, Link, Message, Summary, User
from .gemini_client import summarize_conversations

settings = get_settings()
TZ = ZoneInfo(settings.TIMEZONE)


def _range_for(period: str, ref: date) -> tuple[datetime, datetime, date, date]:
    if period == "daily":
        start_d = ref
        end_d = ref
    elif period == "weekly":
        start_d = ref - timedelta(days=ref.weekday())
        end_d = start_d + timedelta(days=6)
    else:
        raise ValueError(period)
    start = datetime.combine(start_d, time.min, tzinfo=TZ).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    end = datetime.combine(end_d, time.max, tzinfo=TZ).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return start, end, start_d, end_d


def _fetch_lines(db: Session, group_id: int | None, start: datetime, end: datetime) -> list[str]:
    q = (
        db.query(Message, User)
        .outerjoin(User, Message.user_id == User.id)
        .filter(and_(Message.sent_at >= start, Message.sent_at <= end))
    )
    if group_id is not None:
        q = q.filter(Message.group_id == group_id)
    q = q.order_by(Message.sent_at.asc())

    lines: list[str] = []
    for msg, user in q.all():
        who = (user.display_name if user else None) or "ไม่ทราบ"
        stamp = msg.sent_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ).strftime("%H:%M")
        if msg.msg_type == "text" and msg.text:
            lines.append(f"[{stamp}] {who}: {msg.text}")
        elif msg.msg_type == "image":
            if msg.ocr_text:
                lines.append(f"[{stamp}] {who}: (รูปภาพ) OCR: {msg.ocr_text}")
            else:
                lines.append(f"[{stamp}] {who}: (รูปภาพ)")
        elif msg.msg_type in ("video", "audio", "file"):
            lines.append(f"[{stamp}] {who}: ({msg.msg_type})")

        for ln in (
            db.query(Link).filter(Link.message_id == msg.id).all()
        ):
            label = ln.title or ln.url
            lines.append(f"    ↳ [{ln.kind}] {label} — {ln.url}")
    return lines


def generate_summary(period: str, ref: date | None = None) -> list[Summary]:
    """Generate summary per group for the given period. Returns created Summary rows."""
    ref = ref or datetime.now(TZ).date()
    start, end, sd, ed = _range_for(period, ref)

    created: list[Summary] = []
    db: Session = SessionLocal()
    try:
        group_ids: list[int | None] = [g.id for g in db.query(Group).all()]
        if not group_ids:
            group_ids = [None]

        for gid in group_ids:
            existing = (
                db.query(Summary)
                .filter_by(group_id=gid, period=period, period_start=sd)
                .first()
            )
            if existing:
                continue
            lines = _fetch_lines(db, gid, start, end)
            if not lines:
                continue
            label = f"{sd.isoformat()}" if period == "daily" else f"{sd.isoformat()} ถึง {ed.isoformat()}"
            content = summarize_conversations(lines, period_label=label) or "\n".join(lines)
            s = Summary(
                group_id=gid,
                period=period,
                period_start=sd,
                period_end=ed,
                content_md=content,
            )
            db.add(s)
            db.commit()
            db.refresh(s)
            created.append(s)
    finally:
        db.close()
    return created


def run_daily() -> None:
    ref = (datetime.now(TZ) - timedelta(days=0)).date()
    generate_summary("daily", ref)


def run_weekly() -> None:
    # Summarize the week that just ended (assumes trigger runs on Monday).
    ref = (datetime.now(TZ) - timedelta(days=1)).date()
    generate_summary("weekly", ref)
