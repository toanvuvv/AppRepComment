"""Reply log query endpoints.

Read-only views over the ``reply_logs`` table. Supports filtering by nick,
outcome, and time window, plus an aggregate ``/stats`` endpoint intended
for the 20-nick operations dashboard.

Security: all routes require the app API key via ``Depends(require_api_key)``.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.nick_live import NickLive
from app.models.reply_log import ReplyLog
from app.models.user import User
from app.schemas.reply_log import ReplyLogResponse, ReplyLogStats

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/reply-logs",
    tags=["reply-logs"],
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _owned_nick_ids(user_id: int, db: Session):
    """Return a subquery of nick_live ids owned by user_id."""
    return db.query(NickLive.id).filter(NickLive.user_id == user_id).subquery()


@router.get("", response_model=list[ReplyLogResponse])
def list_reply_logs(
    nick_live_id: int | None = None,
    outcome: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ReplyLog]:
    """List reply log rows, newest first."""
    owned = _owned_nick_ids(current_user.id, db)
    q = db.query(ReplyLog).filter(ReplyLog.nick_live_id.in_(owned))
    if nick_live_id is not None:
        q = q.filter(ReplyLog.nick_live_id == nick_live_id)
    if outcome:
        q = q.filter(ReplyLog.outcome == outcome)
    if since is not None:
        q = q.filter(ReplyLog.created_at >= since)
    if until is not None:
        q = q.filter(ReplyLog.created_at <= until)
    return (
        q.order_by(ReplyLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/stats", response_model=ReplyLogStats)
def reply_log_stats(
    nick_live_id: int | None = None,
    since: datetime | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReplyLogStats:
    """Aggregate counts and latency percentiles over a time window.

    Default window: last 24 hours.
    """
    until = _now_utc()
    if since is None:
        since = until - timedelta(hours=24)

    owned = _owned_nick_ids(current_user.id, db)
    q = db.query(ReplyLog).filter(
        ReplyLog.created_at >= since,
        ReplyLog.nick_live_id.in_(owned),
    )
    if nick_live_id is not None:
        q = q.filter(ReplyLog.nick_live_id == nick_live_id)
    rows = q.all()

    total = len(rows)
    by_outcome = Counter(r.outcome for r in rows)
    success = by_outcome.get("success", 0)
    failed = by_outcome.get("failed", 0)
    dropped = by_outcome.get("dropped", 0)
    circuit_open = by_outcome.get("circuit_open", 0)
    no_config = by_outcome.get("no_config", 0)

    attempted = success + failed
    success_rate = (success / attempted) if attempted > 0 else 0.0

    non_no_config_total = total - no_config
    cache_hits = sum(1 for r in rows if r.cached_hit)
    cache_hit_rate = (
        (cache_hits / non_no_config_total) if non_no_config_total > 0 else 0.0
    )

    latencies = [r.latency_ms for r in rows if r.latency_ms is not None]
    avg_latency_ms: float | None
    p50_latency_ms: int | None
    p95_latency_ms: int | None
    if latencies:
        latencies_sorted = sorted(latencies)
        avg_latency_ms = sum(latencies_sorted) / len(latencies_sorted)
        p50_latency_ms = latencies_sorted[len(latencies_sorted) // 2]
        p95_idx = min(
            int(len(latencies_sorted) * 0.95),
            len(latencies_sorted) - 1,
        )
        p95_latency_ms = latencies_sorted[p95_idx]
    else:
        avg_latency_ms = None
        p50_latency_ms = None
        p95_latency_ms = None

    return ReplyLogStats(
        total=total,
        success=success,
        failed=failed,
        dropped=dropped,
        circuit_open=circuit_open,
        no_config=no_config,
        success_rate=success_rate,
        cache_hit_rate=cache_hit_rate,
        avg_latency_ms=avg_latency_ms,
        p50_latency_ms=p50_latency_ms,
        p95_latency_ms=p95_latency_ms,
        since=since,
        until=until,
    )
