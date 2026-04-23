"""Fix app_settings UNIQUE constraint for multi-user isolation.

Legacy schema (pre-004) had ``UNIQUE(key)`` because app_settings was
single-tenant. Migration 004 added ``user_id`` but could not change the
constraint (SQLite does not support ALTER CONSTRAINT). Result: any
second user who tries to set a setting key already used by another user
hits ``UNIQUE constraint failed: app_settings.key`` and the request 500s.

This migration:
1. Detects whether the legacy ``UNIQUE(key)`` is still in place.
2. Deduplicates rows on ``(user_id, key)`` if any accidentally slipped
   through (keeping the most recently updated row per pair).
3. Recreates ``app_settings`` with ``UNIQUE(user_id, key)`` using the
   standard SQLite recreate-table pattern.
"""

import logging
import sqlite3

from app.database import engine

logger = logging.getLogger(__name__)


def _legacy_unique_on_key(cursor: sqlite3.Cursor) -> bool:
    """Return True if app_settings still has the old UNIQUE(key) constraint."""
    cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='app_settings'"
    )
    row = cursor.fetchone()
    if row is None:
        return False
    sql = (row[0] or "").lower()
    # Heuristic: legacy schema declares the unique inline on the column, e.g.
    # "key varchar(100) unique not null". New schema uses a table-level
    # CONSTRAINT uq_app_settings_user_key UNIQUE(user_id, key).
    if "uq_app_settings_user_key" in sql:
        return False
    # Also inspect indexes — inline UNIQUE creates an auto index.
    cursor.execute("PRAGMA index_list(app_settings)")
    for _seq, name, unique, _origin, _partial in cursor.fetchall():
        if not unique:
            continue
        cursor.execute(f"PRAGMA index_info({name})")
        cols = [r[2] for r in cursor.fetchall()]
        if cols == ["key"]:
            return True
    return False


def _dedupe_by_user_key(cursor: sqlite3.Cursor) -> int:
    """Keep only the newest row per (user_id, key). Returns #rows deleted."""
    cursor.execute(
        """
        SELECT user_id, key, COUNT(*)
        FROM app_settings
        GROUP BY user_id, key
        HAVING COUNT(*) > 1
        """
    )
    dups = cursor.fetchall()
    if not dups:
        return 0
    deleted = 0
    for user_id, key, _n in dups:
        cursor.execute(
            """
            DELETE FROM app_settings
            WHERE id NOT IN (
                SELECT id FROM app_settings
                WHERE user_id IS ? AND key = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
            )
            AND user_id IS ? AND key = ?
            """,
            (user_id, key, user_id, key),
        )
        deleted += cursor.rowcount
    logger.warning(
        "Migration 008: deduped %d app_settings rows across %d (user_id, key) pairs",
        deleted, len(dups),
    )
    return deleted


def migrate() -> None:
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        if not _legacy_unique_on_key(cur):
            logger.info("Migration 008: app_settings already uses composite UNIQUE — skip")
            return

        cur.execute("PRAGMA foreign_keys = OFF")
        cur.execute("BEGIN")
        try:
            _dedupe_by_user_key(cur)

            cur.executescript(
                """
                CREATE TABLE app_settings_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER
                        REFERENCES users(id) ON DELETE CASCADE,
                    key VARCHAR(100) NOT NULL,
                    value TEXT,
                    updated_at DATETIME,
                    CONSTRAINT uq_app_settings_user_key UNIQUE (user_id, key)
                );
                INSERT INTO app_settings_new (id, user_id, key, value, updated_at)
                    SELECT id, user_id, key, value, updated_at FROM app_settings;
                DROP TABLE app_settings;
                ALTER TABLE app_settings_new RENAME TO app_settings;
                CREATE INDEX ix_app_settings_user_id ON app_settings(user_id);
                """
            )
            raw.commit()
            logger.info("Migration 008: app_settings recreated with UNIQUE(user_id, key)")
        except Exception:
            raw.rollback()
            logger.exception("Migration 008 rolled back")
            raise

        cur.execute("PRAGMA foreign_key_check")
        violations = cur.fetchall()
        if violations:
            logger.error("Migration 008: FK violations: %s", violations)
        cur.execute("PRAGMA foreign_keys = ON")
        logger.info("Migration 008_fix_app_settings_unique complete")
    finally:
        raw.close()
