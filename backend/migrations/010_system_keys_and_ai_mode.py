"""Add users.ai_key_mode and drop legacy per-user / mis-scoped key rows.

* ``users.ai_key_mode`` — VARCHAR(10) NOT NULL DEFAULT 'system'. Values
  are validated at the Pydantic layer (``'own'`` | ``'system'``); skipping
  the CHECK constraint keeps SQLite happy without a table recreate.
* ``app_settings`` rows with ``key='relive_api_key'`` are purged.
* ``app_settings`` rows with ``user_id IS NULL`` and key in
  ``('openai_api_key','openai_model')`` are also purged.
"""

import logging
import sqlite3

from app.database import engine

logger = logging.getLogger(__name__)


def _column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def migrate() -> None:
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        if not _column_exists(cur, "users", "ai_key_mode"):
            cur.execute(
                "ALTER TABLE users ADD COLUMN ai_key_mode "
                "VARCHAR(10) NOT NULL DEFAULT 'system'"
            )
            logger.info("Migration 010: added users.ai_key_mode")
        else:
            logger.info("Migration 010: users.ai_key_mode already present — skip ALTER")

        cur.execute("DELETE FROM app_settings WHERE key = 'relive_api_key'")
        deleted_relive = cur.rowcount
        cur.execute(
            "DELETE FROM app_settings "
            "WHERE user_id IS NULL AND key IN ('openai_api_key','openai_model')"
        )
        deleted_legacy = cur.rowcount

        raw.commit()
        logger.info(
            "Migration 010: removed %d relive rows, %d legacy NULL-scoped openai rows",
            deleted_relive,
            deleted_legacy,
        )
    finally:
        raw.close()
