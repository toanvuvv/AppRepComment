from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReplyLog(Base):
    """Persisted log of every reply attempt by the dispatcher.

    Retained ~24h for debugging and monitoring. Populated by the reply
    dispatcher for success, failure, dropped, cached-hit, circuit-open,
    and no-config outcomes.
    """

    __tablename__ = "reply_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nick_live_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    session_id: Mapped[int] = mapped_column(Integer, nullable=False)
    guest_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    guest_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    comment_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'ai' | 'knowledge' | 'manual'
    reply_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 'success' | 'failed' | 'dropped' | 'circuit_open' | 'no_config'
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    product_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    __table_args__ = (
        Index("ix_reply_logs_nick_created", "nick_live_id", "created_at"),
    )
