import logging
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = logging.getLogger(__name__)

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./database.db")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    # The default QueuePool (size=5, overflow=10 → 15 total) is far too small
    # for an app that runs many concurrent SSE streams + background workers
    # (auto_poster / auto_pinner / live_moderator / comment_scanner) per nick.
    # Bump generously and fail fast so a stuck handler doesn't take 30s to
    # surface and trip the healthcheck.
    pool_size=int(os.getenv("DB_POOL_SIZE", "30")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "60")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "5")),
    pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    """Apply performance and safety pragmas on every new SQLite connection."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _migrate_add_columns() -> None:
    """Add missing columns to existing tables (SQLite doesn't support ADD COLUMN IF NOT EXISTS)."""
    import sqlite3

    conn = sqlite3.connect(SQLALCHEMY_DATABASE_URL.replace("sqlite:///", ""))
    cursor = conn.cursor()

    migrations = [
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

    for table, column, sql in migrations:
        try:
            cursor.execute(f"SELECT {column} FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            try:
                cursor.execute(sql)
                conn.commit()
            except sqlite3.OperationalError as exc:
                logger.warning(
                    "Schema migration failed for %s.%s: %s", table, column, exc
                )

    # --- Data migration: map old *_enabled columns to new schema ---
    # Old columns may or may not exist; check each before running UPDATE.
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
            cursor.execute(f"SELECT {probe_column} FROM nick_live_settings LIMIT 1")
        except sqlite3.OperationalError:
            # Old column does not exist — skip.
            continue
        try:
            cursor.execute(update_sql)
            conn.commit()
        except sqlite3.OperationalError as exc:
            logger.warning(
                "Data migration probe=%s failed: %s", probe_column, exc
            )

    conn.close()


def init_db():
    from app.models import nick_live  # noqa: F401
    from app.models import settings  # noqa: F401
    from app.models import knowledge_product  # noqa: F401
    from app.models import reply_log  # noqa: F401
    from app.models import user  # noqa: F401
    from app.models import seeding  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_add_columns()

    import importlib
    m003 = importlib.import_module("migrations.003_host_comment")
    m003.migrate()

    m004 = importlib.import_module("migrations.004_multi_user")
    m004.migrate()

    m005 = importlib.import_module("migrations.005_seeding")
    m005.migrate()

    m006 = importlib.import_module("migrations.006_drop_legacy_reply_columns")
    m006.migrate()

    m007 = importlib.import_module("migrations.007_add_missing_fks")
    m007.migrate()

    m008 = importlib.import_module("migrations.008_fix_app_settings_unique")
    m008.migrate()

    m009 = importlib.import_module("migrations.009_seeding_clone_health")
    m009.migrate()

    m010 = importlib.import_module("migrations.010_system_keys_and_ai_mode")
    m010.migrate()

    m011 = importlib.import_module("migrations.011_seeding_proxies")
    m011.migrate()
