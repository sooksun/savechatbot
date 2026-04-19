from datetime import datetime, date
from sqlalchemy import (
    BigInteger, String, Text, DateTime, Date, ForeignKey, Integer, Index, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


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


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    line_message_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True, index=True)
    msg_type: Mapped[str] = mapped_column(String(16))  # text, image, sticker, file, link
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    group: Mapped["Group"] = relationship()
    user: Mapped["User"] = relationship()
    category: Mapped["Category"] = relationship()
    links: Mapped[list["Link"]] = relationship(back_populates="message", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_msg_group_sent", "group_id", "sent_at"),)


class Link(Base):
    __tablename__ = "links"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(1024))
    kind: Mapped[str] = mapped_column(String(32))  # youtube, google_drive, canva, other
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)

    message: Mapped["Message"] = relationship(back_populates="links")


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
