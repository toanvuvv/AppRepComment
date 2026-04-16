import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./database.db")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
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
    ]

    for table, column, sql in migrations:
        try:
            cursor.execute(f"SELECT {column} FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            try:
                cursor.execute(sql)
                conn.commit()
            except sqlite3.OperationalError:
                pass

    conn.close()


def init_db():
    from app.models import nick_live  # noqa: F401
    from app.models import settings  # noqa: F401
    from app.models import knowledge_product  # noqa: F401
    from app.models import reply_log  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_add_columns()

    import importlib
    m003 = importlib.import_module("migrations.003_host_comment")
    m003.migrate()
