"""Retention policy for seeding logs.

Deletes ``seeding_logs`` and ``seeding_log_sessions`` rows older than the
configured retention window. Mirrors the pattern in ``app.main`` for
``reply_logs`` retention but with a longer (30-day) horizon since seeding
logs carry more long-term audit value.
"""

import logging
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models.seeding import SeedingLog, SeedingLogSession

logger = logging.getLogger(__name__)


def cleanup_old_seeding_logs(retention_days: int = 30) -> tuple[int, int]:
    """Delete seeding log rows older than ``retention_days``.

    Returns ``(logs_deleted, sessions_deleted)``. Never raises — errors are
    logged so the scheduler loop is not killed.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    try:
        with SessionLocal() as db:
            # Delete child rows first (FK ON DELETE CASCADE would handle this,
            # but explicit deletion lets us report counts and avoids relying
            # on cascade semantics under SQLAlchemy bulk-delete).
            logs_deleted = (
                db.query(SeedingLog)
                .filter(SeedingLog.sent_at < cutoff)
                .delete(synchronize_session=False)
            )
            sessions_deleted = (
                db.query(SeedingLogSession)
                .filter(SeedingLogSession.started_at < cutoff)
                .delete(synchronize_session=False)
            )
            db.commit()
            logger.info(
                "seeding_log cleanup: deleted %d logs, %d sessions older than %s",
                int(logs_deleted or 0),
                int(sessions_deleted or 0),
                cutoff,
            )
            return int(logs_deleted or 0), int(sessions_deleted or 0)
    except Exception:
        logger.exception("seeding_log cleanup error")
        return 0, 0
