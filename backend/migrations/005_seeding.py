"""Create seeding_* tables and add users.max_clones."""

import logging
import sqlite3

from app.database import Base, engine

logger = logging.getLogger(__name__)


def _col_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def migrate() -> None:
    # Import models so Base.metadata knows about them before create_all.
    from app.models import seeding  # noqa: F401

    Base.metadata.create_all(bind=engine)

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        if not _col_exists(cur, "users", "max_clones"):
            cur.execute("ALTER TABLE users ADD COLUMN max_clones INTEGER")
            logger.info("Added users.max_clones")
        raw.commit()
        logger.info("Migration 005_seeding complete")
    finally:
        raw.close()
