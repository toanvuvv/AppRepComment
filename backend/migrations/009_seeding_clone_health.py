"""Add health/status columns to seeding_clones.

Adds:
 - consecutive_failures INTEGER NOT NULL DEFAULT 0
 - last_status          VARCHAR(20) NULL
 - last_error           TEXT NULL
 - auto_disabled        BOOLEAN NOT NULL DEFAULT 0

Idempotent.
"""

import logging
import sqlite3

from app.database import engine

logger = logging.getLogger(__name__)


def _col_exists(cur: sqlite3.Cursor, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def migrate() -> None:
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        adds = [
            ("consecutive_failures",
             "ALTER TABLE seeding_clones ADD COLUMN consecutive_failures "
             "INTEGER NOT NULL DEFAULT 0"),
            ("last_status",
             "ALTER TABLE seeding_clones ADD COLUMN last_status VARCHAR(20)"),
            ("last_error",
             "ALTER TABLE seeding_clones ADD COLUMN last_error TEXT"),
            ("auto_disabled",
             "ALTER TABLE seeding_clones ADD COLUMN auto_disabled "
             "BOOLEAN NOT NULL DEFAULT 0"),
        ]
        for col, sql in adds:
            if not _col_exists(cur, "seeding_clones", col):
                cur.execute(sql)
                logger.info("Added seeding_clones.%s", col)
        raw.commit()
        logger.info("Migration 009_seeding_clone_health complete")
    finally:
        raw.close()
