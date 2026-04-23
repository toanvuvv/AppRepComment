# System Keys & Per-User AI Key Mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Relive API key system-only (admin-managed, shared by all users) and give OpenAI API key a per-user mode (`own` or `system`) chosen by admin, with no silent fallback.

**Architecture:** Add `ai_key_mode` column to `users`. Store system credentials as `user_id=NULL` rows in `app_settings` with dedicated keys (`relive_api_key`, `system_openai_api_key`, `system_openai_model`). Add `SettingsService.resolve_openai_config(mode)` and `get_system_relive_api_key()` resolvers; migrate call-sites. Admin endpoints under `/api/admin/system-keys/*` manage system credentials; user CRUD accepts `ai_key_mode`. Frontend Settings hides the OpenAI key card when the user is in `system` mode and hides Relive from non-admins; a new admin-only "System Keys" section handles system credentials.

**Tech Stack:** FastAPI + SQLAlchemy (SQLite), Pydantic v2, Vite + React 18 + TypeScript + Ant Design, pytest.

**Spec:** `docs/superpowers/specs/2026-04-23-system-keys-and-ai-mode-design.md`

---

## Task 1: Migration 010 — schema and legacy cleanup

**Files:**
- Create: `backend/migrations/010_system_keys_and_ai_mode.py`
- Create: `backend/tests/test_migration_010.py`
- Modify: `backend/migrations/__init__.py` (register migration if applicable — check pattern)

- [ ] **Step 1: Check how migrations are registered**

Run: `rtk ls backend/migrations` and inspect `backend/app/database.py` or `backend/app/main.py` for a `run_migrations()` loop to confirm how new migrations get picked up.

Expected: confirm there is a loop that iterates `001_*.py`, `002_*.py`, ... (naming convention is enough if discovery is filename-based).

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_migration_010.py`:

```python
import sqlite3

import pytest

from app.database import Base, engine


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Spin up a brand-new SQLite DB with the legacy schema that 010 targets."""
    from sqlalchemy import create_engine
    db_path = tmp_path / "test.db"
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr("app.database.engine", test_engine)
    # Build schema matching the state just before migration 010:
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
    from backend.migrations import migration_010_system_keys_and_ai_mode as mig

    mig.migrate()

    cols = _columns(fresh_db, "users")
    assert "ai_key_mode" in cols
    # Column default applies to existing rows.
    defaults = _rows(fresh_db, "SELECT id, ai_key_mode FROM users ORDER BY id")
    assert defaults == [(1, "system"), (2, "system")]

    # Per-user relive rows gone.
    relive = _rows(fresh_db, "SELECT COUNT(*) FROM app_settings WHERE key='relive_api_key'")
    assert relive == [(0,)]

    # Legacy NULL-scoped openai_* rows removed.
    legacy = _rows(
        fresh_db,
        "SELECT COUNT(*) FROM app_settings "
        "WHERE user_id IS NULL AND key IN ('openai_api_key','openai_model')",
    )
    assert legacy == [(0,)]

    # Unrelated per-user openai_api_key preserved.
    kept = _rows(
        fresh_db,
        "SELECT value FROM app_settings WHERE user_id=1 AND key='openai_api_key'",
    )
    assert kept == [("sk-keep",)]


def test_migration_010_is_idempotent(fresh_db):
    from backend.migrations import migration_010_system_keys_and_ai_mode as mig

    mig.migrate()
    mig.migrate()  # running twice must not raise

    cols = _columns(fresh_db, "users")
    assert "ai_key_mode" in cols
```

Note: the import path `backend.migrations.migration_010_...` must match whatever naming the migration runner expects. If the project imports migrations by file stem (e.g. `010_system_keys_and_ai_mode`), adjust the `from backend.migrations import ...` line accordingly. Use the form observed in existing tests for migrations (check `backend/tests/test_migration_004.py` for the convention).

- [ ] **Step 3: Run the test to verify it fails**

Run: `rtk pytest backend/tests/test_migration_010.py -v`
Expected: FAIL — module `010_system_keys_and_ai_mode` not found.

- [ ] **Step 4: Implement the migration**

Create `backend/migrations/010_system_keys_and_ai_mode.py`:

```python
"""Add users.ai_key_mode and drop legacy per-user / mis-scoped key rows.

This migration introduces the per-user AI key mode flag and cleans out
settings rows that the new resolver logic would otherwise see as
ambiguous:

* ``users.ai_key_mode`` — VARCHAR(10) NOT NULL DEFAULT 'system'. Values
  are validated at the Pydantic layer (``'own'`` | ``'system'``); skipping
  the CHECK constraint keeps SQLite happy without a table recreate.
* ``app_settings`` rows with ``key='relive_api_key'`` are purged. Relive
  becomes a system-only credential; admin re-sets after deploy via the
  ``/api/admin/system-keys/relive`` endpoint.
* ``app_settings`` rows with ``user_id IS NULL`` and key in
  ``('openai_api_key','openai_model')`` are also purged so the new
  ``system_openai_*`` keys own the system slot unambiguously.
"""

import logging
import sqlite3

from app.database import engine

logger = logging.getLogger(__name__)


def _column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def migrate() -> None:
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        if not _column_exists(cur, "users", "ai_key_mode"):
            cur.execute(
                "ALTER TABLE users ADD COLUMN ai_key_mode "
                "VARCHAR(10) NOT NULL DEFAULT 'system'"
            )
            logger.info("Migration 010: added users.ai_key_mode")
        else:
            logger.info("Migration 010: users.ai_key_mode already present — skip ALTER")

        cur.execute("DELETE FROM app_settings WHERE key = 'relive_api_key'")
        deleted_relive = cur.rowcount
        cur.execute(
            "DELETE FROM app_settings "
            "WHERE user_id IS NULL AND key IN ('openai_api_key','openai_model')"
        )
        deleted_legacy = cur.rowcount

        raw.commit()
        logger.info(
            "Migration 010: removed %d relive rows, %d legacy NULL-scoped openai rows",
            deleted_relive, deleted_legacy,
        )
    finally:
        raw.close()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `rtk pytest backend/tests/test_migration_010.py -v`
Expected: both tests PASS.

- [ ] **Step 6: Register the migration in the runner**

Open the migration runner (likely `backend/app/main.py` or `backend/migrations/__init__.py`) and add the new file to whatever list/loop drives `migrate()` calls at startup, following the pattern used for `008` and `009`.

- [ ] **Step 7: Commit**

```bash
rtk git add backend/migrations/010_system_keys_and_ai_mode.py \
            backend/tests/test_migration_010.py \
            backend/migrations/__init__.py backend/app/main.py
rtk git commit -m "feat(db): migration 010 — ai_key_mode column, drop legacy key rows"
```

(Only stage the runner file you actually changed in Step 6.)

---

## Task 2: User model and Pydantic schemas — add `ai_key_mode`

**Files:**
- Modify: `backend/app/models/user.py`
- Modify: `backend/app/schemas/user.py`
- Modify: `backend/tests/` (add a small schema test)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_settings_service.py` (or create a new `backend/tests/test_user_schema.py`):

```python
def test_user_create_defaults_ai_key_mode_to_system():
    from app.schemas.user import UserCreate
    u = UserCreate(username="abc", password="password1")
    assert u.ai_key_mode == "system"


def test_user_create_rejects_invalid_ai_key_mode():
    import pytest
    from pydantic import ValidationError
    from app.schemas.user import UserCreate
    with pytest.raises(ValidationError):
        UserCreate(username="abc", password="password1", ai_key_mode="bogus")


def test_user_update_accepts_none_ai_key_mode():
    from app.schemas.user import UserUpdate
    u = UserUpdate()
    assert u.ai_key_mode is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `rtk pytest backend/tests/test_user_schema.py -v` (or wherever you placed them).
Expected: FAIL — `UserCreate` has no `ai_key_mode` field.

- [ ] **Step 3: Update the model**

Edit `backend/app/models/user.py`. Add after the `is_locked` column:

```python
    ai_key_mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default="system"
    )
```

- [ ] **Step 4: Update the schemas**

Edit `backend/app/schemas/user.py`:

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


AiKeyMode = Literal["own", "system"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=1)


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    max_nicks: int | None
    is_locked: bool
    ai_key_mode: AiKeyMode
    created_at: datetime

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=100)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=8, max_length=100)
    max_nicks: int | None = Field(default=None, ge=0)
    ai_key_mode: AiKeyMode = "system"


class UserUpdate(BaseModel):
    max_nicks: int | None = Field(default=None, ge=0)
    is_locked: bool | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=100)
    ai_key_mode: AiKeyMode | None = None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `rtk pytest backend/tests/test_user_schema.py backend/tests/test_settings_service.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add backend/app/models/user.py backend/app/schemas/user.py \
            backend/tests/test_user_schema.py
rtk git commit -m "feat(users): add ai_key_mode column and schema field"
```

---

## Task 3: SettingsService — resolvers and system-scoped setters

**Files:**
- Modify: `backend/app/services/settings_service.py`
- Modify: `backend/tests/test_settings_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_settings_service.py`:

```python
def test_resolve_openai_config_system_reads_system_rows(db):
    from app.services.settings_service import SettingsService

    # System values under user_id=NULL.
    SettingsService(db).set_system_openai_api_key("sys-key")
    SettingsService(db).set_system_openai_model("gpt-4o")
    # A per-user value that must be ignored.
    SettingsService(db, user_id=1).set_setting("openai_api_key", "own-key")
    SettingsService(db, user_id=1).set_setting("openai_model", "gpt-own")

    api_key, model = SettingsService(db, user_id=1).resolve_openai_config("system")
    assert api_key == "sys-key"
    assert model == "gpt-4o"


def test_resolve_openai_config_own_reads_per_user_and_does_not_fallback(db):
    from app.services.settings_service import SettingsService

    SettingsService(db).set_system_openai_api_key("sys-key")
    SettingsService(db).set_system_openai_model("gpt-sys")

    svc1 = SettingsService(db, user_id=1)
    # user 1 has nothing
    assert svc1.resolve_openai_config("own") == (None, None)

    svc1.set_setting("openai_api_key", "own-1")
    svc1.set_setting("openai_model", "gpt-1")
    assert svc1.resolve_openai_config("own") == ("own-1", "gpt-1")


def test_get_system_relive_api_key_is_scope_free(db):
    from app.services.settings_service import SettingsService

    SettingsService(db).set_setting("relive_api_key", "sys-relive")

    # Even when queried via a user-scoped service, we read the system row.
    assert SettingsService(db, user_id=99).get_system_relive_api_key() == "sys-relive"


def test_resolve_openai_config_rejects_unknown_mode(db):
    import pytest
    from app.services.settings_service import SettingsService
    with pytest.raises(ValueError):
        SettingsService(db, user_id=1).resolve_openai_config("bogus")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `rtk pytest backend/tests/test_settings_service.py -v -k resolve_or_system_relive`
Expected: FAIL — methods do not exist yet.

- [ ] **Step 3: Implement the resolvers**

Edit `backend/app/services/settings_service.py`. Inside `class SettingsService`, add after `get_openai_api_key`:

```python
    # --- System-scoped helpers (user_id=NULL) ---

    _SYSTEM_OPENAI_KEY = "system_openai_api_key"
    _SYSTEM_OPENAI_MODEL = "system_openai_model"
    _RELIVE_KEY = "relive_api_key"

    def _get_system_setting(self, key: str) -> str | None:
        row = (
            self._db.query(AppSetting)
            .filter(AppSetting.key == key, AppSetting.user_id.is_(None))
            .first()
        )
        return row.value if row else None

    def _set_system_setting(self, key: str, value: str) -> None:
        row = (
            self._db.query(AppSetting)
            .filter(AppSetting.key == key, AppSetting.user_id.is_(None))
            .first()
        )
        if row:
            row.value = value
        else:
            row = AppSetting(key=key, value=value, user_id=None)
            self._db.add(row)
        self._db.commit()

    def get_system_openai_api_key(self) -> str | None:
        return self._get_system_setting(self._SYSTEM_OPENAI_KEY)

    def get_system_openai_model(self) -> str | None:
        return self._get_system_setting(self._SYSTEM_OPENAI_MODEL)

    def set_system_openai_api_key(self, value: str) -> None:
        self._set_system_setting(self._SYSTEM_OPENAI_KEY, value)

    def set_system_openai_model(self, value: str) -> None:
        self._set_system_setting(self._SYSTEM_OPENAI_MODEL, value)

    def get_system_relive_api_key(self) -> str | None:
        return self._get_system_setting(self._RELIVE_KEY)

    def set_system_relive_api_key(self, value: str) -> None:
        self._set_system_setting(self._RELIVE_KEY, value)

    def resolve_openai_config(self, ai_key_mode: str) -> tuple[str | None, str | None]:
        """Return (api_key, model) per the user's ai_key_mode. No fallback."""
        if ai_key_mode == "system":
            return self.get_system_openai_api_key(), self.get_system_openai_model()
        if ai_key_mode == "own":
            return self.get_openai_api_key(), self.get_setting("openai_model")
        raise ValueError(f"invalid ai_key_mode: {ai_key_mode!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk pytest backend/tests/test_settings_service.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add backend/app/services/settings_service.py backend/tests/test_settings_service.py
rtk git commit -m "feat(settings): add resolve_openai_config and system-scoped helpers"
```

---

## Task 4: Admin endpoints for system keys

**Files:**
- Modify: `backend/app/schemas/settings.py`
- Modify: `backend/app/routers/admin.py`
- Modify: `backend/tests/test_admin.py` (create if missing)

- [ ] **Step 1: Write the failing tests**

Create/extend `backend/tests/test_admin.py`:

```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_non_admin_cannot_get_system_keys(client, seed_user_and_admin):
    token = _login(client, "u1", "password1")
    r = client.get("/api/admin/system-keys", headers=_auth(token))
    assert r.status_code == 403


def test_admin_get_system_keys_reports_unset(client, seed_user_and_admin):
    token = _login(client, "admin1", "password1")
    r = client.get("/api/admin/system-keys", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "relive_api_key_set": False,
        "openai_api_key_set": False,
        "openai_model": None,
    }


def test_admin_put_system_relive(client, seed_user_and_admin):
    token = _login(client, "admin1", "password1")
    r = client.put(
        "/api/admin/system-keys/relive",
        json={"api_key": "sys-relive"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    r = client.get("/api/admin/system-keys", headers=_auth(token))
    assert r.json()["relive_api_key_set"] is True


def test_admin_put_system_openai_persists_and_masks(client, seed_user_and_admin):
    token = _login(client, "admin1", "password1")
    r = client.put(
        "/api/admin/system-keys/openai",
        json={"api_key": "sk-system", "model": "gpt-4o"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    r = client.get("/api/admin/system-keys", headers=_auth(token))
    body = r.json()
    assert body["openai_api_key_set"] is True
    assert body["openai_model"] == "gpt-4o"
    # Never echoes the raw key.
    assert "sk-system" not in r.text
```

Add the `seed_user_and_admin` fixture to `backend/tests/conftest.py` (create if missing):

```python
import pytest
from sqlalchemy.orm import Session

from app.database import SessionLocal, Base, engine
from app.models.user import User
from app.services.auth import hash_password


@pytest.fixture(autouse=True)
def _reset_schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def seed_user_and_admin():
    with SessionLocal() as db:
        db.add_all([
            User(username="u1", password_hash=hash_password("password1"),
                 role="user", ai_key_mode="own"),
            User(username="admin1", password_hash=hash_password("password1"),
                 role="admin", ai_key_mode="own"),
        ])
        db.commit()
    yield
```

**Important:** If `backend/tests/conftest.py` already exists, DO NOT overwrite it — open it and merge the `seed_user_and_admin` fixture only. The `_reset_schema` autouse fixture is likely to conflict with existing per-module DB setup. If an equivalent reset fixture already exists, skip the `_reset_schema` addition; if not, scope it to just this test module by moving it into `test_admin.py` instead of conftest.

- [ ] **Step 2: Run tests to verify they fail**

Run: `rtk pytest backend/tests/test_admin.py -v`
Expected: FAIL — endpoints return 404.

- [ ] **Step 3: Add schemas**

Edit `backend/app/schemas/settings.py` — append:

```python
# --- System Keys (admin-only) ---


class SystemKeysResponse(BaseModel):
    relive_api_key_set: bool
    openai_api_key_set: bool
    openai_model: str | None


class SystemReliveUpdate(BaseModel):
    api_key: str = Field(min_length=1, max_length=500)


class SystemOpenAIUpdate(BaseModel):
    api_key: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=100)
```

- [ ] **Step 4: Add admin endpoints**

Edit `backend/app/routers/admin.py`. Add imports and endpoints:

```python
from app.schemas.settings import (
    SystemKeysResponse,
    SystemOpenAIUpdate,
    SystemReliveUpdate,
)
from app.services.settings_service import SettingsService
from app.services.nick_cache import nick_cache


def _invalidate_all_nick_settings() -> None:
    nick_cache._settings.clear()


@router.get("/system-keys", response_model=SystemKeysResponse)
def get_system_keys(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SystemKeysResponse:
    svc = SettingsService(db)
    return SystemKeysResponse(
        relive_api_key_set=bool(svc.get_system_relive_api_key()),
        openai_api_key_set=bool(svc.get_system_openai_api_key()),
        openai_model=svc.get_system_openai_model(),
    )


@router.put("/system-keys/relive")
def put_system_relive(
    body: SystemReliveUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    SettingsService(db).set_system_relive_api_key(body.api_key)
    _invalidate_all_nick_settings()
    return {"status": "saved"}


@router.put("/system-keys/openai")
def put_system_openai(
    body: SystemOpenAIUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    svc = SettingsService(db)
    svc.set_system_openai_api_key(body.api_key)
    svc.set_system_openai_model(body.model)
    _invalidate_all_nick_settings()
    return {"status": "saved"}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `rtk pytest backend/tests/test_admin.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add backend/app/schemas/settings.py backend/app/routers/admin.py \
            backend/tests/test_admin.py backend/tests/conftest.py
rtk git commit -m "feat(admin): endpoints to read and set system keys"
```

---

## Task 5: Admin user CRUD accepts `ai_key_mode`; list includes per-user own-key flag

**Files:**
- Modify: `backend/app/routers/admin.py`
- Modify: `backend/tests/test_admin.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_admin.py`:

```python
def test_admin_create_user_defaults_to_system_mode(client, seed_user_and_admin):
    token = _login(client, "admin1", "password1")
    r = client.post(
        "/api/admin/users",
        json={"username": "u2", "password": "password1"},
        headers=_auth(token),
    )
    assert r.status_code == 201
    assert r.json()["ai_key_mode"] == "system"


def test_admin_create_user_with_own_mode(client, seed_user_and_admin):
    token = _login(client, "admin1", "password1")
    r = client.post(
        "/api/admin/users",
        json={"username": "u3", "password": "password1", "ai_key_mode": "own"},
        headers=_auth(token),
    )
    assert r.status_code == 201
    assert r.json()["ai_key_mode"] == "own"


def test_admin_patch_user_ai_key_mode_invalidates_cache(client, seed_user_and_admin, monkeypatch):
    from app.services.nick_cache import nick_cache

    calls = []
    monkeypatch.setattr(nick_cache, "invalidate_settings", lambda nid: calls.append(nid))

    token = _login(client, "admin1", "password1")
    # Get u1's id
    r = client.get("/api/admin/users", headers=_auth(token))
    u1 = next(u for u in r.json() if u["username"] == "u1")

    r = client.patch(
        f"/api/admin/users/{u1['id']}",
        json={"ai_key_mode": "system"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert r.json()["ai_key_mode"] == "system"


def test_admin_list_users_includes_openai_own_key_set(client, seed_user_and_admin):
    token = _login(client, "admin1", "password1")
    # Seed a per-user openai key for u1 directly.
    from app.database import SessionLocal
    from app.services.settings_service import SettingsService
    from app.models.user import User as _U
    with SessionLocal() as db:
        u = db.query(_U).filter(_U.username == "u1").first()
        SettingsService(db, user_id=u.id).set_setting("openai_api_key", "sk-u1")

    r = client.get("/api/admin/users", headers=_auth(token))
    assert r.status_code == 200
    rows = {row["username"]: row for row in r.json()}
    assert rows["u1"]["openai_own_key_set"] is True
    assert rows["admin1"]["openai_own_key_set"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `rtk pytest backend/tests/test_admin.py -v`
Expected: FAIL — `ai_key_mode` ignored on create, `openai_own_key_set` missing.

- [ ] **Step 3: Update `create_user` / `update_user` / `list_users`**

Edit `backend/app/routers/admin.py`. Replace `_UserWithCount`, `list_users`, `create_user`, `update_user` with:

```python
from app.models.settings import AppSetting


class _UserWithCount(UserOut):
    nick_count: int
    openai_own_key_set: bool


@router.get("/users", response_model=list[_UserWithCount])
def list_users(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(User, func.count(NickLive.id))
        .outerjoin(NickLive, NickLive.user_id == User.id)
        .group_by(User.id)
        .all()
    )
    own_key_user_ids = {
        uid for (uid,) in db.query(AppSetting.user_id).filter(
            AppSetting.key == "openai_api_key",
            AppSetting.user_id.isnot(None),
            AppSetting.value.isnot(None),
            AppSetting.value != "",
        ).all()
    }
    return [
        _UserWithCount(
            **UserOut.model_validate(u).model_dump(),
            nick_count=int(c),
            openai_own_key_set=u.id in own_key_user_ids,
        )
        for u, c in rows
    ]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="Username already exists")
    u = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role="user",
        max_nicks=body.max_nicks,
        is_locked=False,
        ai_key_mode=body.ai_key_mode,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return UserOut.model_validate(u)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    changed = False
    if body.max_nicks is not None:
        u.max_nicks = body.max_nicks
        changed = True
    if body.is_locked is not None:
        if u.id == admin.id:
            raise HTTPException(status_code=400, detail="Cannot lock yourself")
        u.is_locked = body.is_locked
        changed = True
    if body.new_password is not None:
        u.password_hash = hash_password(body.new_password)
        changed = True
    if body.ai_key_mode is not None and body.ai_key_mode != u.ai_key_mode:
        u.ai_key_mode = body.ai_key_mode
        changed = True
        # Invalidate cached settings for every nick this user owns so the
        # next reply/post cycle re-resolves the key per the new mode.
        from app.models.nick_live import NickLive
        nick_ids = [nid for (nid,) in db.query(NickLive.id)
                    .filter(NickLive.user_id == u.id).all()]
        for nid in nick_ids:
            nick_cache.invalidate_settings(nid)
    if not changed:
        raise HTTPException(status_code=400, detail="No fields to update")
    db.commit()
    db.refresh(u)

    if body.is_locked is not None:
        from app.main import auto_poster, auto_pinner
        if body.is_locked:
            if auto_poster is not None:
                auto_poster.stop_user_nicks(u.id)
            if auto_pinner is not None:
                auto_pinner.stop_user_nicks(u.id)
        else:
            if auto_poster is not None:
                auto_poster.start_user_nicks(u.id)
            if auto_pinner is not None:
                auto_pinner.start_user_nicks(u.id)

    return UserOut.model_validate(u)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk pytest backend/tests/test_admin.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add backend/app/routers/admin.py backend/tests/test_admin.py
rtk git commit -m "feat(admin): user CRUD handles ai_key_mode and exposes own-key flag"
```

---

## Task 6: Expose mode on `/api/auth/me` and `/api/settings/openai`

**Files:**
- Modify: `backend/app/schemas/settings.py`
- Modify: `backend/app/routers/settings.py`
- Modify: `backend/tests/test_admin.py` (or a new file)

Note: `/api/auth/me` already returns `UserOut`, and `UserOut` now includes `ai_key_mode` (Task 2). No change needed there.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_admin.py`:

```python
def test_auth_me_returns_ai_key_mode(client, seed_user_and_admin):
    token = _login(client, "u1", "password1")
    r = client.get("/api/auth/me", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["ai_key_mode"] == "own"


def test_settings_openai_response_exposes_mode_flag(client, seed_user_and_admin):
    token = _login(client, "u1", "password1")
    r = client.get("/api/settings/openai", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["ai_key_mode"] == "own"
    assert body["is_managed_by_admin"] is False


def test_settings_openai_response_flips_when_admin_sets_system(client, seed_user_and_admin):
    admin_token = _login(client, "admin1", "password1")
    # Get u1 id then flip to system
    r = client.get("/api/admin/users", headers=_auth(admin_token))
    u1 = next(u for u in r.json() if u["username"] == "u1")
    client.patch(
        f"/api/admin/users/{u1['id']}",
        json={"ai_key_mode": "system"},
        headers=_auth(admin_token),
    )

    token = _login(client, "u1", "password1")
    r = client.get("/api/settings/openai", headers=_auth(token))
    body = r.json()
    assert body["ai_key_mode"] == "system"
    assert body["is_managed_by_admin"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `rtk pytest backend/tests/test_admin.py -v`
Expected: FAIL — fields missing from `/api/settings/openai` response.

- [ ] **Step 3: Update the response schema**

Edit `backend/app/schemas/settings.py`, replace `OpenAIConfigResponse`:

```python
class OpenAIConfigResponse(BaseModel):
    api_key_set: bool
    model: str | None
    ai_key_mode: Literal["own", "system"]
    is_managed_by_admin: bool
```

Add `from typing import Literal` at the top if not present.

- [ ] **Step 4: Update the endpoint**

Edit `backend/app/routers/settings.py`, replace the `get_openai_config` handler:

```python
@router.get("/openai", response_model=OpenAIConfigResponse)
def get_openai_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OpenAIConfigResponse:
    svc = SettingsService(db, user_id=current_user.id)
    config = svc.get_openai_config()
    return OpenAIConfigResponse(
        **config,
        ai_key_mode=current_user.ai_key_mode,
        is_managed_by_admin=current_user.ai_key_mode == "system",
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `rtk pytest backend/tests/test_admin.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add backend/app/schemas/settings.py backend/app/routers/settings.py \
            backend/tests/test_admin.py
rtk git commit -m "feat(api): expose ai_key_mode on me and openai settings"
```

---

## Task 7: Switch AI call-sites to `resolve_openai_config`

**Files:**
- Modify: `backend/app/services/nick_cache.py`
- Modify: `backend/app/services/settings_service.py` (`update_nick_settings`)
- Modify: `backend/app/routers/settings.py` (`test_ai`)
- Modify: `backend/tests/test_ai_reply_service.py` or new `backend/tests/test_nick_settings_ai_mode.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_nick_settings_ai_mode.py`:

```python
import pytest


def test_update_nick_settings_ai_mode_own_missing_key_raises(db):
    from app.services.settings_service import SettingsService
    from app.models.nick_live import NickLive
    from app.models.user import User

    db.add(User(id=1, username="u", password_hash="h", role="user", ai_key_mode="own"))
    db.add(NickLive(id=10, user_id=1, name="n", cookies="c", shopee_user_id=1))
    db.commit()

    svc = SettingsService(db, user_id=1)
    svc.get_or_create_nick_settings(10)

    with pytest.raises(ValueError, match="own"):
        svc.update_nick_settings(10, reply_mode="ai")


def test_update_nick_settings_ai_mode_system_missing_key_raises(db):
    from app.services.settings_service import SettingsService
    from app.models.nick_live import NickLive
    from app.models.user import User

    db.add(User(id=2, username="u2", password_hash="h", role="user", ai_key_mode="system"))
    db.add(NickLive(id=20, user_id=2, name="n", cookies="c", shopee_user_id=2))
    db.commit()

    svc = SettingsService(db, user_id=2)
    svc.get_or_create_nick_settings(20)

    with pytest.raises(ValueError, match="Admin chưa"):
        svc.update_nick_settings(20, reply_mode="ai")


def test_update_nick_settings_ai_mode_system_succeeds_when_admin_key_set(db):
    from app.services.settings_service import SettingsService
    from app.models.nick_live import NickLive
    from app.models.user import User

    db.add(User(id=3, username="u3", password_hash="h", role="user", ai_key_mode="system"))
    db.add(NickLive(id=30, user_id=3, name="n", cookies="c", shopee_user_id=3))
    db.commit()

    SettingsService(db).set_system_openai_api_key("sys")
    SettingsService(db).set_system_openai_model("gpt-4o")

    svc = SettingsService(db, user_id=3)
    svc.get_or_create_nick_settings(30)
    row = svc.update_nick_settings(30, reply_mode="ai")
    assert row.reply_mode == "ai"
```

Make sure the `db` fixture covers these imports — reuse the one in `test_settings_service.py` or add an equivalent in `conftest.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `rtk pytest backend/tests/test_nick_settings_ai_mode.py -v`
Expected: FAIL — messages don't match; or success case currently fails because `get_openai_api_key` on user 3 returns None.

- [ ] **Step 3: Update `update_nick_settings` validation**

In `backend/app/services/settings_service.py`, inside `update_nick_settings`, replace the `elif reply_mode == "ai":` branch:

```python
            elif reply_mode == "ai":
                from app.models.user import User as _User
                user_row = (
                    self._db.query(_User).filter(_User.id == self._user_id).first()
                    if self._user_id is not None else None
                )
                mode = (user_row.ai_key_mode if user_row else "own")
                api_key, _model = self.resolve_openai_config(mode)
                if not api_key:
                    if mode == "system":
                        raise ValueError("Admin chưa cấu hình System OpenAI key")
                    raise ValueError("Cần cấu hình OpenAI API key (chế độ own)")
```

- [ ] **Step 4: Update `nick_cache._load_settings_sync`**

In `backend/app/services/nick_cache.py`, inside `_load_settings_sync`:

```python
            from app.models.user import User as _User
            user_row = (
                db.query(_User).filter(_User.id == user_id).first()
                if user_id is not None else None
            )
            ai_key_mode = user_row.ai_key_mode if user_row else "own"
            resolved_key, resolved_model = svc.resolve_openai_config(ai_key_mode)
```

Replace these two lines lower in the snapshot construction:

```python
                openai_api_key=svc.get_openai_api_key(),
                openai_model=svc.get_setting("openai_model"),
```

with:

```python
                openai_api_key=resolved_key,
                openai_model=resolved_model,
```

- [ ] **Step 5: Update `test_ai` router**

In `backend/app/routers/settings.py`, replace the `test_ai` handler body:

```python
@router.post("/test-ai")
async def test_ai(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Test OpenAI connection with current config."""
    svc = SettingsService(db, user_id=current_user.id)
    api_key, model = svc.resolve_openai_config(current_user.ai_key_mode)
    if not api_key:
        if current_user.ai_key_mode == "system":
            raise HTTPException(status_code=400, detail="Admin chưa cấu hình System OpenAI key")
        raise HTTPException(status_code=400, detail="OpenAI API Key chưa được cấu hình")
    model = model or "gpt-4o"
    system_prompt = svc.get_system_prompt() or "Bạn là nhân viên CSKH."
    reply = await generate_reply(
        api_key=api_key,
        model=model,
        system_prompt=system_prompt,
        comment_text="Sản phẩm này có ship COD không ạ?",
        guest_name="Khách test",
    )
    if reply is None:
        raise HTTPException(status_code=502, detail="OpenAI không phản hồi. Kiểm tra lại API key và model.")
    return {"reply": reply, "model": model}
```

- [ ] **Step 6: Run the new tests plus existing ones**

Run: `rtk pytest backend/tests/test_nick_settings_ai_mode.py backend/tests/test_settings_service.py backend/tests/test_ai_reply_service.py -v`
Expected: PASS. If any existing test breaks because it relied on the old `get_openai_api_key` path, update it to seed via `set_system_openai_api_key` or set `User.ai_key_mode='own'` appropriately.

- [ ] **Step 7: Commit**

```bash
rtk git add backend/app/services/settings_service.py backend/app/services/nick_cache.py \
            backend/app/routers/settings.py backend/tests/test_nick_settings_ai_mode.py
rtk git commit -m "feat(ai): AI call-sites resolve key by per-user ai_key_mode"
```

---

## Task 8: Switch Relive call-sites to `get_system_relive_api_key`

**Files:**
- Modify: `backend/app/services/auto_pinner.py`
- Modify: `backend/app/routers/knowledge.py`
- Modify: `backend/app/routers/nick_live.py`
- Modify: `backend/tests/test_auto_pinner.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_auto_pinner.py`:

```python
def test_load_api_key_reads_system_scope(monkeypatch):
    from app.services.auto_pinner import AutoPinner
    from app.services.settings_service import SettingsService
    from app.database import SessionLocal, Base, engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        # A rogue per-user row that must be ignored.
        SettingsService(db, user_id=42).set_setting("relive_api_key", "per-user-stale")
        SettingsService(db).set_system_relive_api_key("system-live")

    pinner = AutoPinner()
    assert pinner._load_api_key(42) == "system-live"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `rtk pytest backend/tests/test_auto_pinner.py -v -k load_api_key_reads_system_scope`
Expected: FAIL — `_load_api_key` still reads per-user row.

- [ ] **Step 3: Update `auto_pinner._load_api_key`**

Edit `backend/app/services/auto_pinner.py`. Replace `_load_api_key`:

```python
    def _load_api_key(self, user_id: int) -> str | None:
        """Relive key is system-scoped; user_id kept in signature for compatibility."""
        from app.services.settings_service import SettingsService
        with SessionLocal() as db:
            return SettingsService(db).get_system_relive_api_key()
```

- [ ] **Step 4: Update `knowledge.parse_products_from_relive`**

In `backend/app/routers/knowledge.py`, replace:

```python
    svc = SettingsService(db, user_id=current_user.id)
    api_key = svc.get_setting("relive_api_key")
```

with:

```python
    svc = SettingsService(db, user_id=current_user.id)
    api_key = svc.get_system_relive_api_key()
```

- [ ] **Step 5: Update `nick_live.host_get_credentials`**

In `backend/app/routers/nick_live.py` around line 485, replace:

```python
    svc = SettingsService(db, user_id=current_user.id)
    api_key = svc.get_setting("relive_api_key")
```

with:

```python
    svc = SettingsService(db, user_id=current_user.id)
    api_key = svc.get_system_relive_api_key()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `rtk pytest backend/tests/test_auto_pinner.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
rtk git add backend/app/services/auto_pinner.py backend/app/routers/knowledge.py \
            backend/app/routers/nick_live.py backend/tests/test_auto_pinner.py
rtk git commit -m "feat(relive): consumers read system-scoped relive_api_key"
```

---

## Task 9: Remove user-facing Relive endpoints; enforce 403 on OpenAI PUT when system mode

**Files:**
- Modify: `backend/app/routers/settings.py`
- Modify: `backend/tests/test_admin.py` (add more cases)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_admin.py`:

```python
def test_user_relive_routes_are_gone(client, seed_user_and_admin):
    token = _login(client, "u1", "password1")
    r = client.get("/api/settings/relive-api-key", headers=_auth(token))
    assert r.status_code == 404
    r = client.put(
        "/api/settings/relive-api-key", json={"api_key": "x"}, headers=_auth(token),
    )
    assert r.status_code == 404


def test_user_in_system_mode_cannot_put_own_openai(client, seed_user_and_admin):
    admin = _login(client, "admin1", "password1")
    r = client.get("/api/admin/users", headers=_auth(admin))
    u1 = next(u for u in r.json() if u["username"] == "u1")
    client.patch(
        f"/api/admin/users/{u1['id']}", json={"ai_key_mode": "system"},
        headers=_auth(admin),
    )

    token = _login(client, "u1", "password1")
    r = client.put(
        "/api/settings/openai",
        json={"api_key": "sk", "model": "gpt-4o"},
        headers=_auth(token),
    )
    assert r.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `rtk pytest backend/tests/test_admin.py -v`
Expected: FAIL — relive routes still exist; openai PUT still returns 200.

- [ ] **Step 3: Delete the user-facing Relive endpoints**

In `backend/app/routers/settings.py`, delete both handlers (`get_relive_key` and `update_relive_key`) and the `# --- Relive API key ---` header block entirely.

- [ ] **Step 4: Enforce 403 in `update_openai_config`**

Replace `update_openai_config` with:

```python
@router.put("/openai")
def update_openai_config(
    payload: OpenAIConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if current_user.ai_key_mode == "system":
        raise HTTPException(
            status_code=403,
            detail="Tài khoản đang dùng system key; không thể tự cấu hình",
        )
    svc = SettingsService(db, user_id=current_user.id)
    svc.set_setting("openai_api_key", payload.api_key)
    svc.set_setting("openai_model", payload.model)
    _invalidate_all_nick_settings()
    return {"status": "saved"}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `rtk pytest backend/tests/test_admin.py backend/tests/test_settings_service.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add backend/app/routers/settings.py backend/tests/test_admin.py
rtk git commit -m "feat(api): remove user-facing Relive routes; gate OpenAI PUT on system mode"
```

---

## Task 10: Frontend API clients

**Files:**
- Modify: `frontend/src/api/settings.ts`
- Modify: `frontend/src/api/admin.ts`

- [ ] **Step 1: Update settings client**

In `frontend/src/api/settings.ts`:

- Replace `OpenAIConfig` interface:

```typescript
export type AiKeyMode = "own" | "system";

export interface OpenAIConfig {
  api_key_set: boolean;
  model: string | null;
  ai_key_mode: AiKeyMode;
  is_managed_by_admin: boolean;
}
```

- Remove the two Relive functions entirely:

```typescript
// DELETE:
//   export async function getReliveApiKey(): ...
//   export async function updateReliveApiKey(...): ...
```

- [ ] **Step 2: Update admin client**

Rewrite `frontend/src/api/admin.ts`:

```typescript
import apiClient from "./client";

export type AiKeyMode = "own" | "system";

export interface AdminUser {
  id: number;
  username: string;
  role: "admin" | "user";
  max_nicks: number | null;
  is_locked: boolean;
  created_at: string;
  nick_count: number;
  ai_key_mode: AiKeyMode;
  openai_own_key_set: boolean;
}

export async function listUsers(): Promise<AdminUser[]> {
  const { data } = await apiClient.get<AdminUser[]>("/admin/users");
  return data;
}

export async function createUser(body: {
  username: string;
  password: string;
  max_nicks: number | null;
  ai_key_mode?: AiKeyMode;
}): Promise<AdminUser> {
  const { data } = await apiClient.post<AdminUser>("/admin/users", body);
  return data;
}

export async function updateUser(
  id: number,
  body: {
    max_nicks?: number | null;
    is_locked?: boolean;
    new_password?: string;
    ai_key_mode?: AiKeyMode;
  }
): Promise<AdminUser> {
  const { data } = await apiClient.patch<AdminUser>(`/admin/users/${id}`, body);
  return data;
}

export async function deleteUser(id: number): Promise<void> {
  await apiClient.delete(`/admin/users/${id}`);
}

// --- System keys (admin only) ---

export interface SystemKeysStatus {
  relive_api_key_set: boolean;
  openai_api_key_set: boolean;
  openai_model: string | null;
}

export async function getSystemKeys(): Promise<SystemKeysStatus> {
  const { data } = await apiClient.get<SystemKeysStatus>("/admin/system-keys");
  return data;
}

export async function updateSystemRelive(api_key: string): Promise<void> {
  await apiClient.put("/admin/system-keys/relive", { api_key });
}

export async function updateSystemOpenAI(
  api_key: string,
  model: string
): Promise<void> {
  await apiClient.put("/admin/system-keys/openai", { api_key, model });
}
```

- [ ] **Step 3: Type-check the frontend**

Run: `cd frontend && rtk pnpm tsc --noEmit`
Expected: clean, or only errors in `Settings.tsx` / `AdminUsers.tsx` that the next tasks will fix.

- [ ] **Step 4: Commit**

```bash
rtk git add frontend/src/api/settings.ts frontend/src/api/admin.ts
rtk git commit -m "feat(frontend): api clients for system keys and ai_key_mode"
```

---

## Task 11: Settings.tsx — conditional rendering and admin system-keys section

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`

- [ ] **Step 1: Identify the auth/role source**

Run: `rtk grep -n "useAuth\|role ===\|current_user\|currentUser" frontend/src`
Expected: spot the pattern the app uses to get the logged-in user (context hook, store, etc.). Use that in the next steps. If nothing exists and `Settings.tsx` needs to fetch `/api/auth/me`, use `apiClient.get("/auth/me")` on mount.

- [ ] **Step 2: Rewrite `Settings.tsx`**

Replace the contents of `frontend/src/pages/Settings.tsx` with:

```tsx
// frontend/src/pages/Settings.tsx
import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Input,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from "antd";
import { ThunderboltOutlined } from "@ant-design/icons";
import {
  getOpenAIConfig,
  getSystemPrompt,
  testAI,
  updateOpenAIConfig,
  updateSystemPrompt,
  type AiKeyMode,
} from "../api/settings";
import {
  getBannedWords,
  getKnowledgeAIConfig,
  updateBannedWords,
  updateKnowledgeAIConfig,
} from "../api/knowledge";
import {
  getSystemKeys,
  updateSystemOpenAI,
  updateSystemRelive,
  type SystemKeysStatus,
} from "../api/admin";
import apiClient from "../api/client";

const { Title, Text } = Typography;
const { TextArea } = Input;

const OPENAI_MODELS = [
  { value: "gpt-4o", label: "GPT-4o" },
  { value: "gpt-4o-mini", label: "GPT-4o Mini" },
  { value: "gpt-3.5-turbo", label: "GPT-3.5 Turbo" },
];

interface Me {
  id: number;
  username: string;
  role: "admin" | "user";
  ai_key_mode: AiKeyMode;
}

function Settings() {
  // Identity
  const [me, setMe] = useState<Me | null>(null);

  // Per-user OpenAI (own mode only)
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("gpt-4o");
  const [apiKeySet, setApiKeySet] = useState(false);
  const [openaiLoading, setOpenaiLoading] = useState(false);
  const [testLoading, setTestLoading] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  // System prompt
  const [systemPrompt, setSystemPrompt] = useState("");
  const [promptLoading, setPromptLoading] = useState(false);

  // Knowledge AI config
  const [knowledgePrompt, setKnowledgePrompt] = useState("");
  const [knowledgeModel, setKnowledgeModel] = useState("gpt-4o");
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);

  // Banned words
  const [bannedWordsText, setBannedWordsText] = useState("");
  const [bannedWordsLoading, setBannedWordsLoading] = useState(false);

  // Admin-only: system keys
  const [sysKeys, setSysKeys] = useState<SystemKeysStatus | null>(null);
  const [sysRelive, setSysRelive] = useState("");
  const [sysOpenAIKey, setSysOpenAIKey] = useState("");
  const [sysOpenAIModel, setSysOpenAIModel] = useState("gpt-4o");
  const [sysReliveLoading, setSysReliveLoading] = useState(false);
  const [sysOpenAILoading, setSysOpenAILoading] = useState(false);

  const loadAll = useCallback(async () => {
    try {
      const meRes = await apiClient.get<Me>("/auth/me");
      setMe(meRes.data);

      const [oai, prompt, banned, kbConfig] = await Promise.all([
        getOpenAIConfig(),
        getSystemPrompt(),
        getBannedWords(),
        getKnowledgeAIConfig(),
      ]);
      setApiKeySet(oai.api_key_set);
      setModel(oai.model || "gpt-4o");
      setSystemPrompt(prompt.prompt);
      setBannedWordsText(banned.words.join("\n"));
      setKnowledgePrompt(kbConfig.system_prompt);
      setKnowledgeModel(kbConfig.model || "gpt-4o");

      if (meRes.data.role === "admin") {
        const sk = await getSystemKeys();
        setSysKeys(sk);
        setSysOpenAIModel(sk.openai_model || "gpt-4o");
      }
    } catch {
      message.error("Không thể tải cài đặt");
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const handleSaveOpenAI = async () => {
    if (!apiKey.trim()) {
      message.error("Nhập API key");
      return;
    }
    setOpenaiLoading(true);
    try {
      await updateOpenAIConfig(apiKey, model);
      message.success("Đã lưu cấu hình OpenAI");
      setApiKey("");
      await loadAll();
    } catch {
      message.error("Lưu thất bại");
    } finally {
      setOpenaiLoading(false);
    }
  };

  const handleTestAI = async () => {
    setTestLoading(true);
    setTestResult(null);
    try {
      const result = await testAI();
      setTestResult(`[${result.model}] ${result.reply}`);
      message.success("AI hoạt động!");
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response
        ?.data?.detail;
      setTestResult(null);
      message.error(detail || "Test AI thất bại");
    } finally {
      setTestLoading(false);
    }
  };

  const handleSavePrompt = async () => {
    setPromptLoading(true);
    try {
      await updateSystemPrompt(systemPrompt);
      message.success("Đã lưu system prompt");
    } catch {
      message.error("Lưu thất bại");
    } finally {
      setPromptLoading(false);
    }
  };

  const handleSaveKnowledgeConfig = async () => {
    setKnowledgeLoading(true);
    try {
      await updateKnowledgeAIConfig({
        system_prompt: knowledgePrompt,
        model: knowledgeModel,
      });
      message.success("Đã lưu cấu hình Knowledge AI");
    } catch {
      message.error("Lưu thất bại");
    } finally {
      setKnowledgeLoading(false);
    }
  };

  const handleSaveBannedWords = async () => {
    setBannedWordsLoading(true);
    try {
      const words = bannedWordsText
        .split("\n")
        .map((w) => w.trim())
        .filter((w) => w.length > 0);
      await updateBannedWords(words);
      message.success("Đã lưu từ cấm");
    } catch {
      message.error("Lưu thất bại");
    } finally {
      setBannedWordsLoading(false);
    }
  };

  const handleSaveSysRelive = async () => {
    if (!sysRelive.trim()) {
      message.error("Nhập Relive API key");
      return;
    }
    setSysReliveLoading(true);
    try {
      await updateSystemRelive(sysRelive);
      setSysRelive("");
      await loadAll();
      message.success("Đã lưu System Relive key");
    } catch {
      message.error("Lưu thất bại");
    } finally {
      setSysReliveLoading(false);
    }
  };

  const handleSaveSysOpenAI = async () => {
    if (!sysOpenAIKey.trim()) {
      message.error("Nhập System OpenAI API key");
      return;
    }
    setSysOpenAILoading(true);
    try {
      await updateSystemOpenAI(sysOpenAIKey, sysOpenAIModel);
      setSysOpenAIKey("");
      await loadAll();
      message.success("Đã lưu System OpenAI key");
    } catch {
      message.error("Lưu thất bại");
    } finally {
      setSysOpenAILoading(false);
    }
  };

  if (!me) return null;
  const isAdmin = me.role === "admin";
  const usingSystemKey = me.ai_key_mode === "system";

  return (
    <div>
      <Title level={3}>Cài đặt</Title>

      {/* Per-user OpenAI Config — hidden entirely in system mode */}
      {usingSystemKey ? (
        <Card style={{ marginBottom: 16 }}>
          <Space direction="vertical">
            <Space>
              <Tag color="blue">AI key: hệ thống</Tag>
              <Text>Tài khoản đang dùng OpenAI key do admin cấu hình.</Text>
            </Space>
            <Button
              icon={<ThunderboltOutlined />}
              onClick={handleTestAI}
              loading={testLoading}
            >
              Test AI (dùng key hệ thống)
            </Button>
            {testResult && (
              <Card size="small" style={{ marginTop: 8, background: "#f6ffed" }}>
                <Text strong>AI reply: </Text>
                <Text>{testResult}</Text>
              </Card>
            )}
          </Space>
        </Card>
      ) : (
        <Card title="Cấu hình OpenAI (key riêng)" style={{ marginBottom: 16 }}>
          {apiKeySet && (
            <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
              API Key đã được lưu. Nhập key mới để thay thế.
            </Text>
          )}
          <Space direction="vertical" style={{ width: "100%" }}>
            <Input.Password
              placeholder="Nhập OpenAI API Key (sk-...)"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            <Select
              style={{ width: 200 }}
              value={model}
              options={OPENAI_MODELS}
              onChange={setModel}
            />
            <Space>
              <Button type="primary" onClick={handleSaveOpenAI} loading={openaiLoading}>
                Lưu cấu hình OpenAI
              </Button>
              <Button
                icon={<ThunderboltOutlined />}
                onClick={handleTestAI}
                loading={testLoading}
                disabled={!apiKeySet}
              >
                Test AI
              </Button>
            </Space>
            {testResult && (
              <Card size="small" style={{ marginTop: 8, background: "#f6ffed" }}>
                <Text strong>AI reply: </Text>
                <Text>{testResult}</Text>
              </Card>
            )}
          </Space>
        </Card>
      )}

      {/* System Prompt */}
      <Card title="System Prompt (Prompt cha cho AI)" style={{ marginBottom: 16 }}>
        <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
          AI sẽ dùng prompt này để trả lời comment của khách hàng.
        </Text>
        <TextArea
          rows={5}
          placeholder="Ví dụ: Bạn là nhân viên CSKH..."
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
        />
        <Button
          type="primary"
          onClick={handleSavePrompt}
          loading={promptLoading}
          style={{ marginTop: 8 }}
        >
          Lưu System Prompt
        </Button>
      </Card>

      {/* Knowledge AI Config */}
      <Card title="Cấu hình Knowledge AI (AI + dữ liệu sản phẩm)" style={{ marginBottom: 16 }}>
        <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
          Cấu hình riêng cho chế độ Knowledge Reply.
        </Text>
        <Space direction="vertical" style={{ width: "100%" }}>
          <TextArea
            rows={5}
            placeholder="Ví dụ: Bạn là nhân viên tư vấn trên Shopee Live..."
            value={knowledgePrompt}
            onChange={(e) => setKnowledgePrompt(e.target.value)}
          />
          <Space>
            <Text>Model:</Text>
            <Select
              style={{ width: 200 }}
              value={knowledgeModel}
              options={OPENAI_MODELS}
              onChange={setKnowledgeModel}
            />
          </Space>
          <Button type="primary" onClick={handleSaveKnowledgeConfig} loading={knowledgeLoading}>
            Lưu cấu hình Knowledge AI
          </Button>
        </Space>
      </Card>

      {/* Banned Words */}
      <Card title="Từ cấm (Banned Words)" style={{ marginBottom: 16 }}>
        <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
          Các từ này sẽ được thay thế bằng *** trong reply AI. Mỗi từ 1 dòng.
        </Text>
        <TextArea
          rows={4}
          placeholder={"Nhập từ cấm, mỗi từ 1 dòng"}
          value={bannedWordsText}
          onChange={(e) => setBannedWordsText(e.target.value)}
        />
        <Button
          type="primary"
          onClick={handleSaveBannedWords}
          loading={bannedWordsLoading}
          style={{ marginTop: 8 }}
        >
          Lưu từ cấm
        </Button>
      </Card>

      {/* Admin-only: System Keys */}
      {isAdmin && (
        <>
          <Title level={4} style={{ marginTop: 32 }}>
            System Keys (admin)
          </Title>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="Key hệ thống dùng chung cho toàn bộ user."
            description="Relive key áp dụng cho mọi user. System OpenAI key chỉ dùng cho user được admin gán mode 'system'."
          />

          <Card title="System Relive API Key" style={{ marginBottom: 16 }}>
            {sysKeys?.relive_api_key_set && (
              <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
                <Tag color="green">Đã cấu hình</Tag> Nhập key mới để thay thế.
              </Text>
            )}
            <Space>
              <Input.Password
                placeholder={sysKeys?.relive_api_key_set ? "Nhập key mới để thay thế" : "Relive API key"}
                value={sysRelive}
                onChange={(e) => setSysRelive(e.target.value)}
                style={{ width: 400 }}
              />
              <Button type="primary" onClick={handleSaveSysRelive} loading={sysReliveLoading}>
                Lưu
              </Button>
            </Space>
          </Card>

          <Card title="System OpenAI Key" style={{ marginBottom: 16 }}>
            {sysKeys?.openai_api_key_set && (
              <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
                <Tag color="green">Đã cấu hình</Tag> Nhập key mới để thay thế.
              </Text>
            )}
            <Space direction="vertical" style={{ width: "100%" }}>
              <Input.Password
                placeholder="sk-..."
                value={sysOpenAIKey}
                onChange={(e) => setSysOpenAIKey(e.target.value)}
              />
              <Select
                style={{ width: 200 }}
                value={sysOpenAIModel}
                options={OPENAI_MODELS}
                onChange={setSysOpenAIModel}
              />
              <Button type="primary" onClick={handleSaveSysOpenAI} loading={sysOpenAILoading}>
                Lưu System OpenAI
              </Button>
            </Space>
          </Card>
        </>
      )}
    </div>
  );
}

export default Settings;
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && rtk pnpm tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Manual smoke test**

Start frontend+backend locally. Log in as:
- non-admin `ai_key_mode='own'` → sees "Cấu hình OpenAI (key riêng)" card, no Relive, no System Keys section.
- non-admin `ai_key_mode='system'` → sees the `"AI key: hệ thống"` banner card (no input), can still click Test AI.
- admin → sees own OpenAI card per their mode + the "System Keys" section with Relive + System OpenAI.

- [ ] **Step 5: Commit**

```bash
rtk git add frontend/src/pages/Settings.tsx
rtk git commit -m "feat(frontend): Settings conditional rendering and system-keys section"
```

---

## Task 12: AdminUsers.tsx — mode column and create-form field

**Files:**
- Modify: `frontend/src/pages/AdminUsers.tsx`

- [ ] **Step 1: Update the page**

Replace the existing page with:

```tsx
import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from "antd";
import { useEffect, useState } from "react";
import {
  AdminUser,
  AiKeyMode,
  createUser,
  deleteUser,
  listUsers,
  updateUser,
} from "../api/admin";

const MODE_OPTIONS = [
  { value: "system", label: "System (dùng key admin)" },
  { value: "own", label: "Own (tự cấu hình)" },
];

export default function AdminUsersPage() {
  const [rows, setRows] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [pwdModal, setPwdModal] = useState<AdminUser | null>(null);
  const [createForm] = Form.useForm();
  const [pwdForm] = Form.useForm();

  const refresh = async () => {
    setLoading(true);
    try {
      setRows(await listUsers());
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    refresh();
  }, []);

  const handleCreate = async (v: {
    username: string;
    password: string;
    max_nicks?: number;
    ai_key_mode?: AiKeyMode;
  }) => {
    try {
      await createUser({
        username: v.username,
        password: v.password,
        max_nicks: v.max_nicks === undefined ? null : Number(v.max_nicks),
        ai_key_mode: v.ai_key_mode ?? "system",
      });
      message.success("Đã tạo user");
      setCreateOpen(false);
      createForm.resetFields();
      refresh();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail ?? "Tạo user thất bại");
    }
  };

  const handleToggleLock = async (u: AdminUser) => {
    try {
      await updateUser(u.id, { is_locked: !u.is_locked });
      refresh();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail ?? "Không thể cập nhật");
    }
  };

  const handleQuota = async (u: AdminUser, value: number | null) => {
    try {
      await updateUser(u.id, { max_nicks: value });
      refresh();
    } catch {
      message.error("Không thể cập nhật quota");
    }
  };

  const handleMode = async (u: AdminUser, mode: AiKeyMode) => {
    try {
      await updateUser(u.id, { ai_key_mode: mode });
      message.success("Đã đổi mode");
      refresh();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail ?? "Không đổi được mode");
    }
  };

  const handleReset = async (v: { new_password: string }) => {
    if (!pwdModal) return;
    try {
      await updateUser(pwdModal.id, { new_password: v.new_password });
      message.success("Đã đặt lại mật khẩu");
      setPwdModal(null);
      pwdForm.resetFields();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail ?? "Không thể đặt lại");
    }
  };

  const handleDelete = async (u: AdminUser) => {
    try {
      await deleteUser(u.id);
      message.success("Đã xóa");
      refresh();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail ?? "Xóa thất bại");
    }
  };

  return (
    <Card
      title="Quản lý user"
      extra={<Button type="primary" onClick={() => setCreateOpen(true)}>Tạo user</Button>}
    >
      <Table
        rowKey="id"
        loading={loading}
        dataSource={rows}
        columns={[
          { title: "Username", dataIndex: "username" },
          {
            title: "Role",
            dataIndex: "role",
            render: (r: string) => (
              <Tag color={r === "admin" ? "gold" : "blue"}>{r}</Tag>
            ),
          },
          {
            title: "Nicks",
            render: (_: unknown, u: AdminUser) =>
              `${u.nick_count} / ${u.max_nicks ?? "∞"}`,
          },
          {
            title: "Max nicks",
            render: (_: unknown, u: AdminUser) => (
              <InputNumber
                min={0}
                value={u.max_nicks ?? undefined}
                placeholder="∞"
                onChange={(v) =>
                  handleQuota(u, v === null || v === undefined ? null : Number(v))
                }
              />
            ),
          },
          {
            title: "AI Key Mode",
            render: (_: unknown, u: AdminUser) => (
              <Select
                style={{ width: 200 }}
                value={u.ai_key_mode}
                options={MODE_OPTIONS}
                onChange={(v) => handleMode(u, v as AiKeyMode)}
              />
            ),
          },
          {
            title: "Own key?",
            render: (_: unknown, u: AdminUser) =>
              u.ai_key_mode === "own"
                ? (u.openai_own_key_set ? <Tag color="green">✓</Tag> : <Tag color="red">✗</Tag>)
                : <Tag>—</Tag>,
          },
          {
            title: "Trạng thái",
            render: (_: unknown, u: AdminUser) => (
              <Switch
                checked={!u.is_locked}
                onChange={() => handleToggleLock(u)}
                checkedChildren="Active"
                unCheckedChildren="Locked"
              />
            ),
          },
          {
            title: "Hành động",
            render: (_: unknown, u: AdminUser) => (
              <Space>
                <Button size="small" onClick={() => setPwdModal(u)}>Reset MK</Button>
                <Popconfirm title={`Xóa user ${u.username}?`} onConfirm={() => handleDelete(u)}>
                  <Button size="small" danger>Xóa</Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title="Tạo user mới"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
      >
        <Form
          form={createForm}
          layout="vertical"
          initialValues={{ ai_key_mode: "system" }}
          onFinish={handleCreate}
        >
          <Form.Item
            name="username"
            label="Username"
            rules={[{ required: true, min: 3, max: 50, pattern: /^[A-Za-z0-9_-]+$/, message: "3-50 ký tự, chỉ a-z 0-9 _ -" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="password"
            label="Mật khẩu"
            rules={[{ required: true, min: 8, message: "Tối thiểu 8 ký tự" }]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item name="max_nicks" label="Giới hạn nick (để trống = không giới hạn)">
            <InputNumber min={0} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="ai_key_mode" label="AI Key Mode">
            <Select options={MODE_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`Đặt lại mật khẩu: ${pwdModal?.username ?? ""}`}
        open={!!pwdModal}
        onCancel={() => setPwdModal(null)}
        onOk={() => pwdForm.submit()}
      >
        <Form form={pwdForm} layout="vertical" onFinish={handleReset}>
          <Form.Item name="new_password" label="Mật khẩu mới" rules={[{ required: true, min: 8 }]}>
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && rtk pnpm tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Manual smoke test**

- Open AdminUsers as admin. The mode column select works and persists. The "Own key?" column shows ✓ / ✗ / — correctly. Create-user form defaults to `system`.

- [ ] **Step 4: Commit**

```bash
rtk git add frontend/src/pages/AdminUsers.tsx
rtk git commit -m "feat(frontend): AdminUsers mode column and create-form field"
```

---

## Task 13: End-to-end backend sweep

**Files:**
- None (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `rtk pytest backend/tests -v`
Expected: all PASS. Fix any tests broken by the changes (typically tests that seeded `openai_api_key` expecting user-scope reads; update them to seed explicitly and/or set `User.ai_key_mode="own"`).

- [ ] **Step 2: GitNexus impact check (pre-commit confidence)**

Run (in a separate terminal, but only to confirm — do not commit stale index):

```
rtk npx gitnexus analyze --embeddings
```

Then `rtk gitnexus_detect_changes()` inside the agent to confirm scope.
Expected: no files outside the ones listed in Tasks 1-12.

- [ ] **Step 3: Final commit (if any pending fixups)**

```bash
rtk git status
rtk git commit -m "chore: test sweep for system-keys refactor" # only if there are staged fixes
```

---

## Post-implementation manual QA checklist

After all tasks land, perform on a fresh DB:

1. Run migrations; verify `users.ai_key_mode` default `'system'`, and no `relive_api_key` rows exist.
2. Log in as admin. Go to Settings → System Keys → set Relive + System OpenAI. Confirm "Đã cấu hình" tag.
3. Create a user with default mode (`system`). Log in as that user — no OpenAI card inputs visible, only the "AI key: hệ thống" banner. Click Test AI — receives a reply.
4. Patch the user to `own` via AdminUsers. User refreshes Settings → sees the per-user OpenAI card. Test AI → 400 until they save their own key.
5. Import products from Relive in Knowledge page as a non-admin — works because Relive key is system-scoped.
6. Trigger `host_get_credentials` and auto-pin — both succeed on the system Relive key.
7. Confirm user-facing `/api/settings/relive-api-key` returns 404 and `/api/admin/system-keys/*` returns 403 for non-admin.
