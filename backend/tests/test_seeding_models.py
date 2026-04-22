"""Schema smoke-tests: migration adds expected columns and tables."""
import sqlite3

import pytest

from app.database import engine, init_db
from app.models.seeding import (  # noqa: F401
    SeedingClone,
    SeedingCommentTemplate,
    SeedingLog,
    SeedingLogSession,
)


@pytest.fixture(autouse=True, scope="session")
def _run_migrations():
    """Ensure all migrations (including 005_seeding) have run against the test DB."""
    init_db()


def _table_columns(table: str) -> set[str]:
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in cur.fetchall()}
    finally:
        raw.close()


def test_seeding_clones_schema():
    cols = _table_columns("seeding_clones")
    assert {
        "id", "user_id", "name", "shopee_user_id", "avatar",
        "cookies", "proxy", "last_sent_at", "created_at",
    }.issubset(cols)


def test_seeding_templates_schema():
    cols = _table_columns("seeding_comment_templates")
    assert {"id", "user_id", "content", "enabled", "created_at"}.issubset(cols)


def test_seeding_log_sessions_schema():
    cols = _table_columns("seeding_log_sessions")
    assert {
        "id", "user_id", "nick_live_id", "shopee_session_id",
        "mode", "started_at", "stopped_at",
    }.issubset(cols)


def test_seeding_logs_schema():
    cols = _table_columns("seeding_logs")
    assert {
        "id", "seeding_log_session_id", "clone_id", "template_id",
        "content", "status", "error", "sent_at",
    }.issubset(cols)


def test_users_has_max_clones():
    cols = _table_columns("users")
    assert "max_clones" in cols
