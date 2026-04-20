"""Test migration 004: rename nick_lives.user_id -> shopee_user_id,
add auth user_id to nick_lives and app_settings, seed admin."""

import importlib
import os
import sys
import tempfile

import pytest
from sqlalchemy import create_engine, text


@pytest.fixture()
def isolated_db(monkeypatch, tmp_path):
    """Return a fresh SQLite file URL with env vars set, then clean up."""
    db_file = tmp_path / "test_m004.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "pw12345678")
    yield db_url, db_file


def _fresh_engine(db_url: str):
    return create_engine(db_url, connect_args={"check_same_thread": False})


def _reload_app_modules(db_url: str):
    """Reload app.config, app.services.auth, app.database so they bind to db_url.
    Also purge cached migration modules so they re-import with the new engine."""
    import app.config
    import app.database
    import app.services.auth

    importlib.reload(app.config)
    importlib.reload(app.services.auth)
    importlib.reload(app.database)

    for key in list(sys.modules):
        if key.startswith("migrations."):
            del sys.modules[key]


def test_migration_renames_and_backfills(isolated_db):
    db_url, db_file = isolated_db

    # Seed old-style schema (pre-migration state)
    e = _fresh_engine(db_url)
    with e.begin() as conn:
        conn.execute(text("""
            CREATE TABLE nick_lives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100),
                user_id BIGINT,
                shop_id BIGINT,
                avatar VARCHAR(500),
                cookies TEXT,
                created_at DATETIME
            )
        """))
        conn.execute(text(
            "INSERT INTO nick_lives (name, user_id, cookies) VALUES ('n1', 111, 'c')"
        ))
        conn.execute(text("""
            CREATE TABLE app_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key VARCHAR(100) UNIQUE,
                value TEXT,
                updated_at DATETIME
            )
        """))
        conn.execute(text(
            "INSERT INTO app_settings (key, value) VALUES ('relive_key', 'abc')"
        ))
    e.dispose()

    # Reload app modules to bind to test DB
    _reload_app_modules(db_url)

    # Import fresh migration module (bound to new engine after reload)
    m004 = importlib.import_module("migrations.004_multi_user")

    # Run the migration directly (no need to call full init_db)
    m004.migrate()

    # Verify results using a direct engine to the test DB
    verify_engine = _fresh_engine(db_url)
    with verify_engine.begin() as conn:
        admin = conn.execute(text(
            "SELECT id, role FROM users WHERE username='admin'"
        )).fetchone()
        assert admin is not None, "Admin user was not seeded"
        assert admin[1] == "admin"
        admin_id = admin[0]

        # nick_lives: old Shopee column renamed, new auth user_id added + backfilled
        cols = [
            r[1] for r in conn.execute(
                text("PRAGMA table_info(nick_lives)")
            ).fetchall()
        ]
        assert "shopee_user_id" in cols, "shopee_user_id column missing from nick_lives"
        assert "user_id" in cols, "auth user_id column missing from nick_lives"

        nick = conn.execute(text(
            "SELECT user_id, shopee_user_id FROM nick_lives WHERE name='n1'"
        )).fetchone()
        assert nick[0] == admin_id, "nick_lives.user_id not backfilled to admin"
        assert nick[1] == 111, "shopee_user_id should be original Shopee id 111"

        # app_settings: user_id added + backfilled
        setting = conn.execute(text(
            "SELECT user_id FROM app_settings WHERE key='relive_key'"
        )).fetchone()
        assert setting[0] == admin_id, "app_settings.user_id not backfilled to admin"

    verify_engine.dispose()


def test_migration_idempotent(isolated_db):
    """Running migrate() twice should not raise errors."""
    db_url, _ = isolated_db
    _reload_app_modules(db_url)
    m004 = importlib.import_module("migrations.004_multi_user")
    m004.migrate()
    m004.migrate()  # second call must be a no-op


def test_migration_no_admin_env_empty_db(monkeypatch, tmp_path):
    """With no ADMIN_USERNAME/PASSWORD but also no existing rows, migration warns and continues."""
    db_file = tmp_path / "empty.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    _reload_app_modules(db_url)
    m004 = importlib.import_module("migrations.004_multi_user")
    # Should not raise — empty DB, no orphaned rows
    m004.migrate()
