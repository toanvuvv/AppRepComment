"""Add host_config, host_proxy, host_reply_enabled, host_auto_post_enabled
to nick_live_settings, and nick_live_id to reply_templates / auto_post_templates."""

import logging
import sqlite3

from app.database import Base, engine

logger = logging.getLogger(__name__)


def _col_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def migrate() -> None:
    Base.metadata.create_all(bind=engine)

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        additions = [
            ("nick_live_settings", "host_config", "TEXT"),
            ("nick_live_settings", "host_proxy", "TEXT"),
            ("nick_live_settings", "host_reply_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
            ("nick_live_settings", "host_auto_post_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
        ]
        for table, col, col_type in additions:
            if not _col_exists(cur, table, col):
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                logger.info(f"Added {table}.{col}")

        if not _col_exists(cur, "reply_templates", "nick_live_id"):
            cur.execute("ALTER TABLE reply_templates ADD COLUMN nick_live_id INTEGER")
            logger.info("Added reply_templates.nick_live_id")

        if not _col_exists(cur, "auto_post_templates", "nick_live_id"):
            cur.execute("ALTER TABLE auto_post_templates ADD COLUMN nick_live_id INTEGER")
            logger.info("Added auto_post_templates.nick_live_id")

        raw.commit()
        logger.info("Migration 003_host_comment complete")
    finally:
        raw.close()
