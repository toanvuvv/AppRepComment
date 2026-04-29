import logging
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = logging.getLogger(__name__)

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./database.db")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    # SQLite serializes all writes at the file level, so a huge pool only wastes
    # RAM without improving write throughput. Writes are already funneled through
    # reply_log_writer's queue, so a modest pool is enough for read concurrency
    # (SSE streams + background workers). pool_recycle / pool_pre_ping are
    # meaningless for a file-local SQLite (no network timeout).
    pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "5")),
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
        cursor.execute("PRAGMA mmap_size=134217728")   # 128 MB — DB fits fully in RAM
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA cache_size=-20000")     # 20 MB cache (negative = KB)
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


def init_db():
    from app.models import nick_live  # noqa: F401
    from app.models import settings  # noqa: F401
    from app.models import knowledge_product  # noqa: F401
    from app.models import reply_log  # noqa: F401
    from app.models import user  # noqa: F401
    from app.models import seeding  # noqa: F401

    Base.metadata.create_all(bind=engine)

    import importlib
    import sqlite3
    from pathlib import Path

    from migrations import (
        _db_path,
        ensure_migrations_table,
        is_applied,
        mark_applied,
    )

    migrations_dir = Path(__file__).resolve().parent.parent / "migrations"
    versions = sorted(
        p.stem for p in migrations_dir.glob("[0-9][0-9][0-9]_*.py")
    )

    conn = sqlite3.connect(_db_path())
    try:
        ensure_migrations_table(conn)

        # Backfill schema_migrations on databases that pre-date this tracking
        # mechanism. If schema_migrations is empty but the legacy `users`
        # table already exists, the DB has been running migrations 000-011
        # via the old hand-rolled importlib block — mark them as applied so
        # we do not re-run them. Migration 012+ have their own self-checks
        # and are safe to (re-)run.
        count = conn.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()[0]
        if count == 0:
            existing_tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "users" in existing_tables:
                for v in versions:
                    if v < "012":
                        mark_applied(conn, v)
                logger.info(
                    "Backfilled schema_migrations for legacy DB (versions < 012)"
                )

        applied_now = 0
        for version in versions:
            if is_applied(conn, version):
                continue
            module = importlib.import_module(f"migrations.{version}")
            module.migrate()
            mark_applied(conn, version)
            applied_now += 1
        logger.info("Migrations: %d applied this run", applied_now)
    finally:
        conn.close()
