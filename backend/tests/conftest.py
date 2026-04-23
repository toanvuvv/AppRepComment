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


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset slowapi in-memory counters between tests to prevent 429 bleed-through."""
    try:
        from app.rate_limit import limiter
        limiter.reset()
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _reset_login_attempts():
    """Reset per-IP failed login counters between tests."""
    try:
        from app.services import login_attempts
        login_attempts.reset()
    except Exception:
        pass
    yield


_SEED_USERNAMES = ["usr1", "u1", "usr2", "usr3", "admin1"]
_SYSTEM_KEY_NAMES = ["relive_api_key", "system_openai_api_key", "system_openai_model"]


def _clear_system_keys(db) -> None:
    """Delete all NULL-scoped app_settings rows used as system keys."""
    from app.models.settings import AppSetting
    (
        db.query(AppSetting)
        .filter(AppSetting.user_id.is_(None), AppSetting.key.in_(_SYSTEM_KEY_NAMES))
        .delete(synchronize_session=False)
    )


@pytest.fixture
def seed_user_and_admin():
    """Create a regular user and an admin user for system-keys tests, clean up after."""
    from app.database import Base, SessionLocal, engine
    from app.models.user import User
    from app.services.auth import hash_password

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        _clear_system_keys(db)
        db.query(User).filter(User.username.in_(_SEED_USERNAMES)).delete()
        db.add(User(
            username="usr1",
            password_hash=hash_password("password1"),
            role="user",
            ai_key_mode="own",
        ))
        db.add(User(
            username="u1",
            password_hash=hash_password("password1"),
            role="user",
            ai_key_mode="own",
        ))
        db.add(User(
            username="admin1",
            password_hash=hash_password("password1"),
            role="admin",
            ai_key_mode="own",
        ))
        db.commit()
    yield
    with SessionLocal() as db:
        _clear_system_keys(db)
        db.query(User).filter(User.username.in_(_SEED_USERNAMES)).delete()
        db.commit()
