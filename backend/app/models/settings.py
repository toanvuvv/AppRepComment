# backend/app/models/settings.py
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.crypto import EncryptedString


class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ReplyTemplate(Base):
    __tablename__ = "reply_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    nick_live_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class AutoPostTemplate(Base):
    __tablename__ = "auto_post_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    nick_live_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    max_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class NickLiveSetting(Base):
    __tablename__ = "nick_live_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nick_live_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    ai_reply_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_reply_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_post_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    knowledge_reply_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    moderator_config: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    host_config: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    host_proxy: Mapped[str | None] = mapped_column(Text, nullable=True)
    host_reply_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    host_auto_post_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
