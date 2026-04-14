from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./database.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

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

    Base.metadata.create_all(bind=engine)
    _migrate_add_columns()
