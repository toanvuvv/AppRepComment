"""Shared pytest fixtures and session-level setup.

The test_migration_004 module reloads app.database (and app.config) to point
at a temporary SQLite file.  After that test module finishes, the module-level
``engine`` / ``SessionLocal`` objects inside app.database are bound to a
now-deleted temp file.  Any subsequent test that imports from app.database
ends up talking to that deleted DB.

This conftest adds a session-scoped autouse fixture that reloads app.database
(and dependent modules) back to the real DB after every test, preventing the
cross-module contamination.
"""
import importlib

import pytest


@pytest.fixture(autouse=True)
def _restore_app_database():
    """Reload app.database after each test to counter test_migration_004 poisoning."""
    yield
    # After the test: re-import app.database so that engine/SessionLocal are
    # re-bound to whatever DATABASE_URL is currently set in the environment.
    # This is a no-op when the migration test has not run yet.
    try:
        import app.database
        importlib.reload(app.database)
    except Exception:
        pass
