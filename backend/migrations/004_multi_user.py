"""Add users table, add user_id FK to nick_lives (rename Shopee user_id first)
and app_settings, seed admin from env, backfill existing rows to admin."""

import logging

from app.config import ADMIN_PASSWORD, ADMIN_USERNAME
from app.database import Base, engine
from app.services.auth import hash_password

logger = logging.getLogger(__name__)


def _col_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def _table_exists(cursor, table: str) -> bool:
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cursor.fetchone() is not None


def migrate() -> None:
    # NOTE: Do NOT call Base.metadata.create_all here — it would try to
    # create nick_lives with the new schema (missing Shopee column rename).
    # We create the users table explicitly, do column surgery, then let
    # init_db()'s create_all be a no-op on existing tables.

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        # 0. Ensure users table exists (create_all in init_db handles it,
        #    but migration may run before create_all on first boot).
        if not _table_exists(cur, "users"):
            cur.execute("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(10) NOT NULL DEFAULT 'user',
                    max_nicks INTEGER,
                    is_locked BOOLEAN NOT NULL DEFAULT 0,
                    created_at DATETIME,
                    updated_at DATETIME
                )
            """)
            logger.info("Created users table")

        # 1. Seed admin
        cur.execute("SELECT id FROM users WHERE role='admin' LIMIT 1")
        admin_row = cur.fetchone()
        if admin_row is None:
            orphan_count = 0
            if _table_exists(cur, "nick_lives"):
                cur.execute("SELECT COUNT(*) FROM nick_lives")
                orphan_count = cur.fetchone()[0]

            if not ADMIN_USERNAME or not ADMIN_PASSWORD:
                if orphan_count > 0:
                    raise RuntimeError(
                        "ADMIN_USERNAME and ADMIN_PASSWORD must be set in env — "
                        f"{orphan_count} nick_lives rows exist with no owner"
                    )
                logger.warning(
                    "No admin seeded (ADMIN_USERNAME/ADMIN_PASSWORD empty)"
                )
                admin_id = None
            else:
                cur.execute(
                    "INSERT INTO users (username, password_hash, role, max_nicks, "
                    "is_locked, created_at, updated_at) "
                    "VALUES (?, ?, 'admin', NULL, 0, datetime('now'), datetime('now'))",
                    (ADMIN_USERNAME, hash_password(ADMIN_PASSWORD)),
                )
                admin_id = cur.lastrowid
                logger.info(f"Seeded admin id={admin_id} username={ADMIN_USERNAME}")
        else:
            admin_id = admin_row[0]

        # 2. Rename nick_lives.user_id -> shopee_user_id (if old schema present)
        if _table_exists(cur, "nick_lives"):
            if _col_exists(cur, "nick_lives", "user_id") and not _col_exists(cur, "nick_lives", "shopee_user_id"):
                # SQLite supports RENAME COLUMN since 3.25
                cur.execute("ALTER TABLE nick_lives RENAME COLUMN user_id TO shopee_user_id")
                logger.info("Renamed nick_lives.user_id -> shopee_user_id")

            # 3. Add auth user_id column (nullable first for backfill)
            if not _col_exists(cur, "nick_lives", "user_id"):
                cur.execute("ALTER TABLE nick_lives ADD COLUMN user_id INTEGER")
                if admin_id is not None:
                    cur.execute("UPDATE nick_lives SET user_id=? WHERE user_id IS NULL", (admin_id,))
                cur.execute("CREATE INDEX IF NOT EXISTS ix_nick_lives_user_id ON nick_lives(user_id)")
                logger.info("Added nick_lives.user_id + backfilled")

        # 4. Add user_id to app_settings
        if _table_exists(cur, "app_settings") and not _col_exists(cur, "app_settings", "user_id"):
            cur.execute("ALTER TABLE app_settings ADD COLUMN user_id INTEGER")
            if admin_id is not None:
                cur.execute("UPDATE app_settings SET user_id=? WHERE user_id IS NULL", (admin_id,))
            cur.execute("CREATE INDEX IF NOT EXISTS ix_app_settings_user_id ON app_settings(user_id)")
            logger.info("Added app_settings.user_id + backfilled")

        # 5. Add user_id to reply_templates and auto_post_templates
        for table in ("reply_templates", "auto_post_templates"):
            if _table_exists(cur, table) and not _col_exists(cur, table, "user_id"):
                cur.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER")
                if admin_id is not None:
                    cur.execute(
                        f"UPDATE {table} SET user_id=? WHERE user_id IS NULL",
                        (admin_id,),
                    )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS ix_{table}_user_id ON {table}(user_id)"
                )
                logger.info(f"Added {table}.user_id + backfilled")

        raw.commit()
        logger.info("Migration 004_multi_user complete")
    finally:
        raw.close()
