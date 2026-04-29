"""Legacy column migrations for ``nick_live_settings``.

Originally implemented inline as ``_migrate_add_columns()`` in
``app/database.py``. Moved here so it participates in the ``schema_migrations``
tracking mechanism. Semantics unchanged — each ALTER is guarded by a column
probe so the migration remains idempotent.
"""

import logging
import sqlite3

from migrations import _db_path

logger = logging.getLogger(__name__)


def migrate() -> None:
    db_path = _db_path()
    if not db_path:
        logger.warning("Migration 000: cannot resolve sqlite path, skipping")
        return

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()

        column_migrations = [
            (
                "nick_live_settings",
                "knowledge_reply_enabled",
                "ALTER TABLE nick_live_settings ADD COLUMN knowledge_reply_enabled BOOLEAN NOT NULL DEFAULT 0",
            ),
            (
                "nick_live_settings",
                "moderator_config",
                "ALTER TABLE nick_live_settings ADD COLUMN moderator_config TEXT",
            ),
            (
                "nick_live_settings",
                "reply_mode",
                "ALTER TABLE nick_live_settings ADD COLUMN reply_mode VARCHAR(20) NOT NULL DEFAULT 'none'",
            ),
            (
                "nick_live_settings",
                "reply_to_host",
                "ALTER TABLE nick_live_settings ADD COLUMN reply_to_host BOOLEAN NOT NULL DEFAULT 0",
            ),
            (
                "nick_live_settings",
                "reply_to_moderator",
                "ALTER TABLE nick_live_settings ADD COLUMN reply_to_moderator BOOLEAN NOT NULL DEFAULT 0",
            ),
            (
                "nick_live_settings",
                "auto_post_to_host",
                "ALTER TABLE nick_live_settings ADD COLUMN auto_post_to_host BOOLEAN NOT NULL DEFAULT 0",
            ),
            (
                "nick_live_settings",
                "auto_post_to_moderator",
                "ALTER TABLE nick_live_settings ADD COLUMN auto_post_to_moderator BOOLEAN NOT NULL DEFAULT 0",
            ),
            (
                "nick_live_settings",
                "auto_pin_enabled",
                "ALTER TABLE nick_live_settings ADD COLUMN auto_pin_enabled BOOLEAN NOT NULL DEFAULT 0",
            ),
            (
                "nick_live_settings",
                "pin_min_interval_minutes",
                "ALTER TABLE nick_live_settings ADD COLUMN pin_min_interval_minutes INTEGER NOT NULL DEFAULT 2",
            ),
            (
                "nick_live_settings",
                "pin_max_interval_minutes",
                "ALTER TABLE nick_live_settings ADD COLUMN pin_max_interval_minutes INTEGER NOT NULL DEFAULT 5",
            ),
        ]

        for table, column, sql in column_migrations:
            try:
                cursor.execute(f"SELECT {column} FROM {table} LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    cursor.execute(sql)
                    conn.commit()
                except sqlite3.OperationalError as exc:
                    logger.warning(
                        "Schema migration failed for %s.%s: %s",
                        table, column, exc,
                    )

        # --- Data migration: map old *_enabled columns to new schema ---
        data_migrations: list[tuple[str, str]] = [
            (
                "knowledge_reply_enabled",
                "UPDATE nick_live_settings SET reply_mode = 'knowledge' WHERE knowledge_reply_enabled = 1",
            ),
            (
                "ai_reply_enabled",
                "UPDATE nick_live_settings SET reply_mode = 'ai' "
                "WHERE ai_reply_enabled = 1 AND "
                "(knowledge_reply_enabled IS NULL OR knowledge_reply_enabled = 0)",
            ),
            (
                "auto_reply_enabled",
                "UPDATE nick_live_settings SET reply_to_moderator = 1 WHERE auto_reply_enabled = 1",
            ),
            (
                "host_reply_enabled",
                "UPDATE nick_live_settings SET reply_to_host = 1 WHERE host_reply_enabled = 1",
            ),
            (
                "auto_post_enabled",
                "UPDATE nick_live_settings SET auto_post_to_moderator = 1 WHERE auto_post_enabled = 1",
            ),
            (
                "host_auto_post_enabled",
                "UPDATE nick_live_settings SET auto_post_to_host = 1 WHERE host_auto_post_enabled = 1",
            ),
        ]

        for probe_column, update_sql in data_migrations:
            try:
                cursor.execute(
                    f"SELECT {probe_column} FROM nick_live_settings LIMIT 1"
                )
            except sqlite3.OperationalError:
                continue
            try:
                cursor.execute(update_sql)
                conn.commit()
            except sqlite3.OperationalError as exc:
                logger.warning(
                    "Data migration probe=%s failed: %s", probe_column, exc
                )
    finally:
        conn.close()
