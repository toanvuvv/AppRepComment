"""Migration tracking helpers.

Each migration module exposes a ``migrate()`` function. The runner in
``app.database.init_db`` discovers files matching ``NNN_*.py`` and applies
them in order, recording applied versions in the ``schema_migrations`` table.
"""

import os
import sqlite3

from sqlalchemy.engine.url import make_url


def _db_path() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./database.db")
    return make_url(url).database


def ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def is_applied(conn: sqlite3.Connection, version: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
    )
    return cur.fetchone() is not None


def mark_applied(conn: sqlite3.Connection, version: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
        (version,),
    )
    conn.commit()
