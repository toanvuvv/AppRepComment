"""Test migration 010: add users.ai_key_mode and drop legacy key rows."""

import importlib
import sys

import pytest
from sqlalchemy import create_engine


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Spin up a brand-new SQLite DB with the legacy schema that 010 targets."""
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"

    monkeypatch.setenv("DATABASE_URL", db_url)

    # Reload app modules so engine binds to our temp DB.
    import app.config
    import app.database

    importlib.reload(app.config)
    importlib.reload(app.database)

    # Purge any cached migration 010 module so it re-imports with new engine.
    for key in list(sys.modules):
        if "010" in key:
            del sys.modules[key]

    test_engine = create_engine(db_url, connect_args={"check_same_thread": False})

    raw = test_engine.raw_connection()
    cur = raw.cursor()
    cur.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(10) NOT NULL DEFAULT 'user',
            max_nicks INTEGER,
            max_clones INTEGER,
            is_locked BOOLEAN NOT NULL DEFAULT 0,
            created_at DATETIME,
            updated_at DATETIME
        );
        CREATE TABLE app_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            key VARCHAR(100) NOT NULL,
            value TEXT,
            updated_at DATETIME,
            CONSTRAINT uq_app_settings_user_key UNIQUE (user_id, key)
        );
        INSERT INTO users (id, username, password_hash, role)
            VALUES (1, 'u1', 'h', 'user'), (2, 'u2', 'h', 'admin');
        INSERT INTO app_settings (user_id, key, value)
            VALUES (1, 'relive_api_key', 'legacy-u1'),
                   (2, 'relive_api_key', 'legacy-u2'),
                   (1, 'openai_api_key', 'sk-keep'),
                   (NULL, 'openai_api_key', 'should-be-removed'),
                   (NULL, 'openai_model', 'gpt-old');
        """
    )
    raw.commit()
    raw.close()

    yield test_engine

    test_engine.dispose()


def _columns(engine, table):
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        return {r[1]: r for r in cur.fetchall()}
    finally:
        raw.close()


def _rows(engine, sql, params=()):
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        raw.close()


def test_migration_010_adds_ai_key_mode_and_clears_legacy_rows(fresh_db):
    mig = importlib.import_module("migrations.010_system_keys_and_ai_mode")

    mig.migrate()

    cols = _columns(fresh_db, "users")
    assert "ai_key_mode" in cols

    defaults = _rows(fresh_db, "SELECT id, ai_key_mode FROM users ORDER BY id")
    assert defaults == [(1, "system"), (2, "system")]

    relive = _rows(fresh_db, "SELECT COUNT(*) FROM app_settings WHERE key='relive_api_key'")
    assert relive == [(0,)]

    legacy = _rows(
        fresh_db,
        "SELECT COUNT(*) FROM app_settings "
        "WHERE user_id IS NULL AND key IN ('openai_api_key','openai_model')",
    )
    assert legacy == [(0,)]

    kept = _rows(
        fresh_db,
        "SELECT value FROM app_settings WHERE user_id=1 AND key='openai_api_key'",
    )
    assert kept == [("sk-keep",)]


def test_migration_010_is_idempotent(fresh_db):
    mig = importlib.import_module("migrations.010_system_keys_and_ai_mode")

    mig.migrate()
    mig.migrate()  # running twice must not raise

    cols = _columns(fresh_db, "users")
    assert "ai_key_mode" in cols
