from datetime import datetime, date
from sqlalchemy import (
    BigInteger, Boolean, String, Text, DateTime, Date, ForeignKey, Integer, Index, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class DashboardUser(Base):
    __tablename__ = "dashboard_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="viewer")  # admin | viewer
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    line_group_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    line_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    picture_url: Mapped[str | None] = mapped_column(String(512), nullable=True)


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_auto: Mapped[int] = mapped_column(Integer, default=0)  # 1 = discovered by Gemini


class WebhookRawEvent(Base):
    __tablename__ = "webhook_raw_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    source_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # group, user, room
    line_group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    line_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    webhook_event_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    payload: Mapped[str] = mapped_column(Text)  # raw JSON
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class GroupMember(Base):
    __tablename__ = "group_members"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    left_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    group: Mapped["Group"] = relationship()
    user: Mapped["User"] = relationship()

    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_member"),)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    line_message_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True, index=True)
    webhook_event_id: Mapped[int | None] = mapped_column(ForeignKey("webhook_raw_events.id"), nullable=True)
    msg_type: Mapped[str] = mapped_column(String(16))  # text, image, sticker, file, link
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_unsent: Mapped[bool] = mapped_column(Boolean, default=False)
    unsent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    group: Mapped["Group"] = relationship()
    user: Mapped["User"] = relationship()
    category: Mapped["Category"] = relationship()
    links: Mapped[list["Link"]] = relationship(back_populates="message", cascade="all, delete-orphan")
    tags: Mapped[list["MessageTag"]] = relationship(cascade="all, delete-orphan")

    __table_args__ = (Index("ix_msg_group_sent", "group_id", "sent_at"),)


class Link(Base):
    __tablename__ = "links"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(1024))
    kind: Mapped[str] = mapped_column(String(32))  # youtube, google_drive, canva, other
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    message: Mapped["Message"] = relationship(back_populates="links")


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    color: Mapped[str] = mapped_column(String(16), default="#6366f1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MessageTag(Base):
    __tablename__ = "message_tags"
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    tag: Mapped["Tag"] = relationship()


class Entity(Base):
    __tablename__ = "entities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # person, org, place, date, topic, money, other
    name: Mapped[str] = mapped_column(String(255), index=True)
    normalized: Mapped[str] = mapped_column(String(255), index=True)
    mention_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("kind", "normalized", name="uq_entity_kind_name"),)


class EntityMention(Base):
    __tablename__ = "entity_mentions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    entity: Mapped["Entity"] = relationship()
    message: Mapped["Message"] = relationship()
    __table_args__ = (UniqueConstraint("entity_id", "message_id", name="uq_em"),)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(String(512))
    decided_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    message: Mapped["Message"] = relationship()


class ActionItem(Base):
    __tablename__ = "action_items"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True, index=True)
    task: Mapped[str] = mapped_column(String(512))
    assignee: Mapped[str | None] = mapped_column(String(128), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open, done, cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    message: Mapped["Message"] = relationship()


class Summary(Base):
    __tablename__ = "summaries"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True, index=True)
    period: Mapped[str] = mapped_column(String(16))  # daily, weekly
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date)
    content_md: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("group_id", "period", "period_start", name="uq_summary_scope"),)
