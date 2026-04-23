"""Drop legacy NOT NULL columns on nick_live_settings that no longer
appear in the model and block INSERTs for new rows.

Columns dropped:
- ai_reply_enabled    (replaced by reply_mode = 'ai')
- auto_reply_enabled  (replaced by reply_to_moderator)

Data from these columns has already been copied into the new schema by
the data-migration block in app/database.py, so dropping them is safe.
"""

import logging
import sqlite3

from app.database import engine

logger = logging.getLogger(__name__)


def _col_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def migrate() -> None:
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        for col in ("ai_reply_enabled", "auto_reply_enabled"):
            if _col_exists(cur, "nick_live_settings", col):
                cur.execute(f"ALTER TABLE nick_live_settings DROP COLUMN {col}")
                logger.info(f"Dropped nick_live_settings.{col}")
        raw.commit()
        logger.info("Migration 006_drop_legacy_reply_columns complete")
    finally:
        raw.close()
