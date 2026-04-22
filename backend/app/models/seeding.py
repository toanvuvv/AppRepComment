"""ORM models for the Seeding feature.

Clones (per-user pool) post Shopee ``type: 100`` guest comments into live
sessions owned by one of the user's own host nicks. The host's uuid/usersig
(from NickLiveSetting.host_config) are borrowed at send time; clones supply
cookies + identity only.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.crypto import EncryptedString


class SeedingClone(Base):
    __tablename__ = "seeding_clones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    shopee_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    avatar: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cookies: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    proxy: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False,
    )


class SeedingCommentTemplate(Base):
    __tablename__ = "seeding_comment_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False,
    )


class SeedingLogSession(Base):
    __tablename__ = "seeding_log_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    nick_live_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("nick_lives.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    shopee_session_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 'manual' | 'auto'
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False,
    )
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index(
            "ix_seeding_log_sessions_user_session_mode",
            "user_id", "shopee_session_id", "mode",
        ),
    )


class SeedingLog(Base):
    __tablename__ = "seeding_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seeding_log_session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("seeding_log_sessions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    clone_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seeding_clones.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("seeding_comment_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 'success' | 'failed' | 'rate_limited'
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False,
    )
