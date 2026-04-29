"""Enable INCREMENTAL auto_vacuum on the SQLite database.

PRAGMA auto_vacuum can only take effect after a full VACUUM following the
PRAGMA assignment, so this migration:

1. Inspects current ``PRAGMA auto_vacuum`` — if already 2 (INCREMENTAL),
   skips and returns immediately.
2. Otherwise sets ``PRAGMA auto_vacuum=INCREMENTAL`` and runs ``VACUUM``.
   VACUUM rewrites the database file and briefly locks it; it only needs
   to run once.

The migration is idempotent and never raises — failures are logged as
warnings so they cannot block app startup.
"""

import logging
import sqlite3

from sqlalchemy.engine.url import make_url

from app.database import SQLALCHEMY_DATABASE_URL

logger = logging.getLogger(__name__)

_INCREMENTAL = 2


def migrate() -> None:
    db_path = make_url(SQLALCHEMY_DATABASE_URL).database
    if not db_path:
        logger.warning("Migration 012: cannot resolve sqlite path, skipping")
        return

    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error as exc:
        logger.warning("Migration 012: connect failed (%s) — skipping", exc)
        return

    try:
        cursor = conn.cursor()
        try:
            current = cursor.execute("PRAGMA auto_vacuum").fetchone()
            current_mode = current[0] if current else None
        except sqlite3.Error as exc:
            logger.warning("Migration 012: read auto_vacuum failed (%s) — skipping", exc)
            return

        if current_mode == _INCREMENTAL:
            logger.info("Migration 012: auto_vacuum already INCREMENTAL — skip")
            return

        logger.info(
            "Migration 012: enabling auto_vacuum=INCREMENTAL, running VACUUM "
            "(may take a moment)..."
        )
        try:
            cursor.execute("PRAGMA auto_vacuum=INCREMENTAL")
            # VACUUM cannot run inside a transaction.
            conn.isolation_level = None
            cursor.execute("VACUUM")
            conn.isolation_level = ""
            logger.info("Migration 012: auto_vacuum=INCREMENTAL enabled")
        except sqlite3.Error as exc:
            logger.warning("Migration 012: VACUUM failed (%s) — continuing", exc)
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass
