"""Add missing FOREIGN KEY constraints on nick_live_id columns.

Tables affected (FK to nick_lives.id with ON DELETE CASCADE):
- reply_templates.nick_live_id
- auto_post_templates.nick_live_id
- nick_live_settings.nick_live_id

SQLite does not support ALTER TABLE ADD CONSTRAINT, so we use the
recommended 12-step recreate-table pattern:
https://www.sqlite.org/lang_altertable.html#otheralter

Before recreating, orphaned rows (nick_live_id pointing to a deleted
nick_lives.id) are deleted to satisfy the new FK constraint. The number
of deleted rows is logged for audit.
"""

import logging
import sqlite3

from app.database import engine

logger = logging.getLogger(__name__)


def _fk_already_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA foreign_key_list({table})")
    for row in cursor.fetchall():
        # row: (id, seq, table, from, to, on_update, on_delete, match)
        if row[3] == column and row[2] == "nick_lives":
            return True
    return False


def _cleanup_orphans(cursor: sqlite3.Cursor, table: str, column: str) -> int:
    """Delete rows whose nick_live_id points to a non-existent nick_lives.id.

    Returns the number of rows deleted.
    """
    cursor.execute(
        f"SELECT COUNT(*) FROM {table} "
        f"WHERE {column} IS NOT NULL "
        f"AND {column} NOT IN (SELECT id FROM nick_lives)"
    )
    (orphan_count,) = cursor.fetchone()
    if orphan_count > 0:
        cursor.execute(
            f"DELETE FROM {table} "
            f"WHERE {column} IS NOT NULL "
            f"AND {column} NOT IN (SELECT id FROM nick_lives)"
        )
        logger.warning(
            "Migration 007: deleted %d orphaned rows from %s", orphan_count, table
        )
    return int(orphan_count)


def _recreate_reply_templates(cursor: sqlite3.Cursor) -> None:
    if _fk_already_exists(cursor, "reply_templates", "nick_live_id"):
        return
    _cleanup_orphans(cursor, "reply_templates", "nick_live_id")
    cursor.executescript(
        """
        CREATE TABLE reply_templates_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            nick_live_id INTEGER
                REFERENCES nick_lives(id) ON DELETE CASCADE,
            user_id INTEGER
                REFERENCES users(id) ON DELETE CASCADE,
            created_at DATETIME
        );
        INSERT INTO reply_templates_new (id, content, nick_live_id, user_id, created_at)
            SELECT id, content, nick_live_id, user_id, created_at
            FROM reply_templates;
        DROP TABLE reply_templates;
        ALTER TABLE reply_templates_new RENAME TO reply_templates;
        CREATE INDEX ix_reply_templates_user_id ON reply_templates(user_id);
        CREATE INDEX ix_reply_templates_nick_live_id ON reply_templates(nick_live_id);
        """
    )
    logger.info("Migration 007: reply_templates recreated with FK")


def _recreate_auto_post_templates(cursor: sqlite3.Cursor) -> None:
    if _fk_already_exists(cursor, "auto_post_templates", "nick_live_id"):
        return
    _cleanup_orphans(cursor, "auto_post_templates", "nick_live_id")
    cursor.executescript(
        """
        CREATE TABLE auto_post_templates_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            nick_live_id INTEGER
                REFERENCES nick_lives(id) ON DELETE CASCADE,
            user_id INTEGER
                REFERENCES users(id) ON DELETE CASCADE,
            min_interval_seconds INTEGER NOT NULL DEFAULT 60,
            max_interval_seconds INTEGER NOT NULL DEFAULT 300,
            created_at DATETIME
        );
        INSERT INTO auto_post_templates_new
            (id, content, nick_live_id, user_id,
             min_interval_seconds, max_interval_seconds, created_at)
            SELECT id, content, nick_live_id, user_id,
                   min_interval_seconds, max_interval_seconds, created_at
            FROM auto_post_templates;
        DROP TABLE auto_post_templates;
        ALTER TABLE auto_post_templates_new RENAME TO auto_post_templates;
        CREATE INDEX ix_auto_post_templates_user_id ON auto_post_templates(user_id);
        CREATE INDEX ix_auto_post_templates_nick_live_id ON auto_post_templates(nick_live_id);
        """
    )
    logger.info("Migration 007: auto_post_templates recreated with FK")


def _recreate_nick_live_settings(cursor: sqlite3.Cursor) -> None:
    if _fk_already_exists(cursor, "nick_live_settings", "nick_live_id"):
        return
    _cleanup_orphans(cursor, "nick_live_settings", "nick_live_id")

    # Dynamically enumerate columns so this works regardless of prior ADD COLUMN
    # migrations (which may have added optional fields).
    cursor.execute("PRAGMA table_info(nick_live_settings)")
    cols = cursor.fetchall()  # (cid, name, type, notnull, dflt, pk)

    # Build column definitions preserving type/notnull/default, but rewriting
    # nick_live_id to carry the FK.
    col_defs: list[str] = []
    col_names: list[str] = []
    for _cid, name, ctype, notnull, dflt, pk in cols:
        col_names.append(name)
        if name == "id":
            col_defs.append("id INTEGER PRIMARY KEY AUTOINCREMENT")
            continue
        if name == "nick_live_id":
            col_defs.append(
                "nick_live_id INTEGER NOT NULL UNIQUE "
                "REFERENCES nick_lives(id) ON DELETE CASCADE"
            )
            continue
        parts = [name, ctype or "TEXT"]
        if notnull:
            parts.append("NOT NULL")
        if dflt is not None:
            parts.append(f"DEFAULT {dflt}")
        col_defs.append(" ".join(parts))

    cols_sql = ", ".join(col_defs)
    names_sql = ", ".join(col_names)
    cursor.executescript(
        f"""
        CREATE TABLE nick_live_settings_new ({cols_sql});
        INSERT INTO nick_live_settings_new ({names_sql})
            SELECT {names_sql} FROM nick_live_settings;
        DROP TABLE nick_live_settings;
        ALTER TABLE nick_live_settings_new RENAME TO nick_live_settings;
        """
    )
    logger.info("Migration 007: nick_live_settings recreated with FK")


def migrate() -> None:
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        # FK enforcement must be off during recreation; the ON-delete action
        # only applies going forward.
        cur.execute("PRAGMA foreign_keys = OFF")
        cur.execute("BEGIN")
        try:
            _recreate_reply_templates(cur)
            _recreate_auto_post_templates(cur)
            _recreate_nick_live_settings(cur)
            raw.commit()
        except Exception:
            raw.rollback()
            logger.exception("Migration 007 rolled back")
            raise
        # Validate referential integrity after recreation.
        cur.execute("PRAGMA foreign_key_check")
        violations = cur.fetchall()
        if violations:
            logger.error("Migration 007: FK violations detected: %s", violations)
        cur.execute("PRAGMA foreign_keys = ON")
        logger.info("Migration 007_add_missing_fks complete")
    finally:
        raw.close()
