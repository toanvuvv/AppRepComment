"""Create seeding_proxies table and add seeding_clones.proxy_id.

Idempotent.
"""

import logging
import sqlite3

from app.database import engine

logger = logging.getLogger(__name__)


def _col_exists(cur: sqlite3.Cursor, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def _table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def migrate() -> None:
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        if not _table_exists(cur, "seeding_proxies"):
            cur.execute(
                """
                CREATE TABLE seeding_proxies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL
                        REFERENCES users(id) ON DELETE CASCADE,
                    scheme VARCHAR(10) NOT NULL,
                    host VARCHAR(255) NOT NULL,
                    port INTEGER NOT NULL,
                    username VARCHAR(255),
                    password TEXT,
                    note VARCHAR(255),
                    created_at DATETIME NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX ix_seeding_proxies_user_id "
                "ON seeding_proxies(user_id)"
            )
            cur.execute(
                "CREATE UNIQUE INDEX ux_seeding_proxies_unique "
                "ON seeding_proxies(user_id, scheme, host, port, "
                "COALESCE(username, ''))"
            )
            logger.info("Created seeding_proxies table")

        if not _col_exists(cur, "seeding_clones", "proxy_id"):
            cur.execute(
                "ALTER TABLE seeding_clones ADD COLUMN proxy_id INTEGER "
                "REFERENCES seeding_proxies(id) ON DELETE SET NULL"
            )
            cur.execute(
                "CREATE INDEX ix_seeding_clones_proxy_id "
                "ON seeding_clones(proxy_id)"
            )
            logger.info("Added seeding_clones.proxy_id")

        raw.commit()
        logger.info("Migration 011_seeding_proxies complete")
    finally:
        raw.close()
