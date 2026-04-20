# Multi-User Auth & Admin Management — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace single shared API key with multi-user auth (JWT), add admin role that can create/lock/delete users and cap each user's nick quota; each user manages their own Relive + AI settings.

**Architecture:** FastAPI dependency `get_current_user` extracts JWT from `Authorization: Bearer` header or `?token=` query (SSE). All resource routers filter by `user_id`. Admin role gates `/api/admin/users`. Frontend stores JWT in `localStorage`, attaches it via axios interceptor, redirects to `/login` on 401/403.

**Tech Stack:** Python (FastAPI, SQLAlchemy, SQLite), `passlib[bcrypt]`, `python-jose[cryptography]`, `slowapi` (rate limit). Frontend React 18 + antd 5 + axios + react-router-dom 6.

**Design spec:** `docs/superpowers/specs/2026-04-20-multi-user-auth-design.md`

**Scope note on per-user isolation:**
`knowledge_products`, `reply_logs`, `nick_live_settings` are keyed by `nick_live_id` and cascade through nick ownership — they do **not** need a direct `user_id` column. Only `nick_lives` (owner) and `app_settings` (per-user Relive/AI config) get `user_id` columns. API filters on these tables check `nick_live_id IN (SELECT id FROM nick_lives WHERE user_id = current_user.id)`.

---

## File Structure

**New backend files:**
- `backend/app/models/user.py` — `User` model
- `backend/app/schemas/user.py` — `LoginRequest`, `LoginResponse`, `UserOut`, `UserCreate`, `UserUpdate`, `ChangePasswordRequest`
- `backend/app/services/auth.py` — bcrypt hash/verify, JWT encode/decode
- `backend/app/routers/auth.py` — `/api/auth/*`
- `backend/app/routers/admin.py` — `/api/admin/users`
- `backend/migrations/004_multi_user.py` — add users table, seed admin, backfill user_id
- `backend/tests/test_auth_service.py`, `test_auth_router.py`, `test_admin_router.py`, `test_user_isolation.py`, `test_quota.py`

**Modified backend files:**
- `backend/requirements.txt` — add `passlib[bcrypt]`, `python-jose[cryptography]`, `slowapi`
- `backend/app/dependencies.py` — add `get_current_user`, `require_admin`; deprecate `require_api_key`
- `backend/app/config.py` — add `JWT_SECRET`, `JWT_TTL_HOURS`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`
- `backend/app/database.py` — register new models, run new migration
- `backend/app/main.py` — include new routers, seed admin in lifespan
- `backend/app/models/nick_live.py` — add `user_id` FK
- `backend/app/models/settings.py` — add `user_id` to `AppSetting`, change unique to `(user_id, key)`
- `backend/app/routers/nick_live.py` — filter by `user_id`, enforce quota
- `backend/app/routers/settings.py` — scope to current user
- `backend/app/routers/knowledge.py` — scope via nick ownership
- `backend/app/routers/reply_logs.py` — scope via nick ownership
- `backend/app/services/auto_poster.py` — add `stop_user_nicks`, `start_user_nicks`
- `backend/app/services/live_moderator.py` — add `drop_user(user_id)`

**New frontend files:**
- `frontend/src/contexts/AuthContext.tsx` — auth provider + hook
- `frontend/src/components/ProtectedRoute.tsx`, `AdminRoute.tsx`
- `frontend/src/pages/Login.tsx`, `ChangePassword.tsx`, `AdminUsers.tsx`
- `frontend/src/api/auth.ts`, `admin.ts`

**Modified frontend files:**
- `frontend/src/api/client.ts` — JWT interceptor
- `frontend/src/App.tsx` — login route, protected routes, admin route
- `frontend/src/main.tsx` — wrap in `AuthProvider`
- `frontend/src/components/Layout.tsx` — user dropdown (depends on current layout)

---

### Task 1: Install auth dependencies

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Edit `backend/requirements.txt`**

Add after existing entries:

```
passlib[bcrypt]>=1.7.4
python-jose[cryptography]>=3.3.0
slowapi>=0.1.9
```

- [ ] **Step 2: Install**

Run: `cd backend && pip install -r requirements.txt`
Expected: installs without errors.

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\toanvuvv\Desktop\BysCom\App Rep Comment"
rtk git add backend/requirements.txt
rtk git commit -m "chore: add auth deps (passlib, jose, slowapi)"
```

---

### Task 2: Add config values

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: Read current config**

Run: `cat backend/app/config.py` to see existing pattern.

- [ ] **Step 2: Append config entries**

Add at the end of `backend/app/config.py`:

```python
import os

# --- Auth config ---
JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-insecure-change-me")
JWT_ALGORITHM: str = "HS256"
JWT_TTL_HOURS: int = int(os.getenv("JWT_TTL_HOURS", "8"))

ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")
ENV: str = os.getenv("ENV", "development")

if ENV != "development" and JWT_SECRET == "dev-insecure-change-me":
    raise RuntimeError("JWT_SECRET must be set in non-dev environments")
```

(If `os` is already imported at the top, remove the duplicate `import os` line.)

- [ ] **Step 3: Commit**

```bash
rtk git add backend/app/config.py
rtk git commit -m "feat(auth): add JWT and admin seed config"
```

---

### Task 3: User model

**Files:**
- Create: `backend/app/models/user.py`
- Modify: `backend/app/database.py` (register new model)

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_user_model.py`:

```python
from app.database import Base, engine, SessionLocal
from app.models.user import User


def test_user_model_persists(tmp_path, monkeypatch):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        u = User(
            username="alice",
            password_hash="x",
            role="user",
            max_nicks=5,
            is_locked=False,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        assert u.id is not None
        assert u.username == "alice"
        assert u.max_nicks == 5
        db.delete(u)
        db.commit()
```

- [ ] **Step 2: Run test — expect FAIL (no `user.py`)**

Run: `cd backend && pytest tests/test_user_model.py -v`
Expected: `ModuleNotFoundError: No module named 'app.models.user'`

- [ ] **Step 3: Implement the model**

Create `backend/app/models/user.py`:

```python
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False, default="user")
    max_nicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
```

- [ ] **Step 4: Register model in `init_db()`**

In `backend/app/database.py` `init_db()` function, add:

```python
from app.models import user  # noqa: F401
```

next to the other `from app.models import ...` imports.

- [ ] **Step 5: Run test — expect PASS**

Run: `cd backend && pytest tests/test_user_model.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add backend/app/models/user.py backend/app/database.py backend/tests/test_user_model.py
rtk git commit -m "feat(auth): add User model"
```

---

### Task 4: Auth service — password hashing

**Files:**
- Create: `backend/app/services/auth.py`
- Test: `backend/tests/test_auth_service.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_auth_service.py`:

```python
import pytest
from app.services.auth import hash_password, verify_password


def test_hash_and_verify():
    h = hash_password("secret123")
    assert h != "secret123"
    assert verify_password("secret123", h) is True
    assert verify_password("wrong", h) is False


def test_hash_is_unique_per_call():
    assert hash_password("abc") != hash_password("abc")
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd backend && pytest tests/test_auth_service.py -v`
Expected: `ImportError`.

- [ ] **Step 3: Implement**

Create `backend/app/services/auth.py`:

```python
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import JWT_ALGORITHM, JWT_SECRET, JWT_TTL_HOURS

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_ctx.verify(plain, hashed)
    except ValueError:
        return False


def create_access_token(*, user_id: int, username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_TTL_HOURS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
```

- [ ] **Step 4: Run test — expect PASS**

Run: `cd backend && pytest tests/test_auth_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add backend/app/services/auth.py backend/tests/test_auth_service.py
rtk git commit -m "feat(auth): add password hash/verify + JWT helpers"
```

---

### Task 5: Auth service — JWT tests

**Files:**
- Modify: `backend/tests/test_auth_service.py`

- [ ] **Step 1: Append JWT tests**

Add to `backend/tests/test_auth_service.py`:

```python
import time
from app.services.auth import create_access_token, decode_access_token


def test_jwt_roundtrip():
    token = create_access_token(user_id=42, username="alice", role="user")
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["username"] == "alice"
    assert payload["role"] == "user"


def test_jwt_tampered_returns_none():
    token = create_access_token(user_id=1, username="a", role="user")
    assert decode_access_token(token + "x") is None


def test_jwt_invalid_returns_none():
    assert decode_access_token("garbage") is None
```

- [ ] **Step 2: Run — expect PASS**

Run: `cd backend && pytest tests/test_auth_service.py -v`
Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
rtk git add backend/tests/test_auth_service.py
rtk git commit -m "test(auth): JWT roundtrip and tamper tests"
```

---

### Task 6: Migration — users table + backfill

**Files:**
- Create: `backend/migrations/004_multi_user.py`
- Modify: `backend/app/database.py` (call new migration in `init_db`)
- Modify: `backend/app/models/nick_live.py` (add `user_id` FK)
- Modify: `backend/app/models/settings.py` (add `user_id` to `AppSetting`)

- [ ] **Step 1: Add `user_id` column to `NickLive` model**

In `backend/app/models/nick_live.py`, inside the `NickLive` class, add after `id`:

```python
    user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True
    )
```

Update the import line to include `ForeignKey`:

```python
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
```

Replace the `user_id` declaration with:

```python
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
```

- [ ] **Step 2: Add `user_id` to `AppSetting`**

In `backend/app/models/settings.py`, change `AppSetting`:

```python
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
# ...

class AppSetting(Base):
    __tablename__ = "app_settings"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_app_settings_user_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
```

Remove the old `unique=True` from `key`.

- [ ] **Step 3: Create migration script**

Create `backend/migrations/004_multi_user.py`:

```python
"""Add users table, add user_id FK to nick_lives and app_settings,
seed admin from env, backfill existing rows to admin."""

import logging
import sqlite3

from app.config import ADMIN_PASSWORD, ADMIN_USERNAME
from app.database import Base, engine
from app.services.auth import hash_password

logger = logging.getLogger(__name__)


def _col_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def _table_exists(cursor, table: str) -> bool:
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cursor.fetchone() is not None


def migrate() -> None:
    Base.metadata.create_all(bind=engine)  # creates `users` table if absent

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        # 1. Seed admin if none exists
        cur.execute("SELECT id FROM users WHERE role='admin' LIMIT 1")
        admin_row = cur.fetchone()
        if admin_row is None:
            if not ADMIN_USERNAME or not ADMIN_PASSWORD:
                # If orphan data exists we must have an admin to attach it to.
                cur.execute("SELECT COUNT(*) FROM nick_lives")
                orphan_count = cur.fetchone()[0]
                if orphan_count > 0:
                    raise RuntimeError(
                        "ADMIN_USERNAME and ADMIN_PASSWORD must be set in env — "
                        f"{orphan_count} nick_lives rows exist with no owner"
                    )
                logger.warning(
                    "No admin user seeded (ADMIN_USERNAME/ADMIN_PASSWORD env empty)"
                )
                admin_id = None
            else:
                cur.execute(
                    "INSERT INTO users (username, password_hash, role, max_nicks, "
                    "is_locked, created_at, updated_at) "
                    "VALUES (?, ?, 'admin', NULL, 0, datetime('now'), datetime('now'))",
                    (ADMIN_USERNAME, hash_password(ADMIN_PASSWORD)),
                )
                admin_id = cur.lastrowid
                logger.info(f"Seeded admin user id={admin_id} username={ADMIN_USERNAME}")
        else:
            admin_id = admin_row[0]

        # 2. Add user_id column to nick_lives (nullable first for backfill)
        if not _col_exists(cur, "nick_lives", "user_id"):
            cur.execute("ALTER TABLE nick_lives ADD COLUMN user_id INTEGER")
            if admin_id is not None:
                cur.execute("UPDATE nick_lives SET user_id=? WHERE user_id IS NULL",
                            (admin_id,))
            cur.execute("CREATE INDEX IF NOT EXISTS ix_nick_lives_user_id ON nick_lives(user_id)")
            logger.info("Added nick_lives.user_id + backfilled")

        # 3. Add user_id column to app_settings
        if not _col_exists(cur, "app_settings", "user_id"):
            cur.execute("ALTER TABLE app_settings ADD COLUMN user_id INTEGER")
            if admin_id is not None:
                cur.execute("UPDATE app_settings SET user_id=? WHERE user_id IS NULL",
                            (admin_id,))
            # SQLite cannot drop old unique(key); leave it — (user_id, key) constraint enforced by ORM.
            cur.execute("CREATE INDEX IF NOT EXISTS ix_app_settings_user_id ON app_settings(user_id)")
            logger.info("Added app_settings.user_id + backfilled")

        raw.commit()
        logger.info("Migration 004_multi_user complete")
    finally:
        raw.close()
```

- [ ] **Step 4: Hook migration into `init_db`**

In `backend/app/database.py` `init_db()`, after the `m003` call add:

```python
    m004 = importlib.import_module("migrations.004_multi_user")
    m004.migrate()
```

Also add the user import right above `Base.metadata.create_all`:

```python
    from app.models import user  # noqa: F401
```

(if not already added in Task 3).

- [ ] **Step 5: Test migration on a scratch DB**

Create `backend/tests/test_migration_004.py`:

```python
import os
import tempfile

from sqlalchemy import text


def test_migration_creates_users_and_backfills(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "pw12345678")

    # Re-import with new env
    import importlib, app.database, app.config, app.services.auth  # noqa
    importlib.reload(app.config)
    importlib.reload(app.database)
    importlib.reload(app.services.auth)
    from app.database import engine, init_db

    # Seed orphan nick row before migration
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS nick_lives ("
            "id INTEGER PRIMARY KEY, name TEXT, user_id_shop INTEGER, "
            "shop_id INTEGER, avatar TEXT, cookies TEXT, created_at TEXT)"
        ))
        conn.execute(text(
            "INSERT INTO nick_lives (name, user_id_shop, cookies) "
            "VALUES ('nick1', 111, 'c')"
        ))

    init_db()

    with engine.begin() as conn:
        r = conn.execute(text("SELECT id, role FROM users WHERE username='admin'")).fetchone()
        assert r is not None
        assert r[1] == "admin"
        admin_id = r[0]

        r2 = conn.execute(text("SELECT user_id FROM nick_lives WHERE name='nick1'")).fetchone()
        assert r2[0] == admin_id

    os.unlink(tmp.name)
```

Note: The pre-existing `nick_lives` column is named `user_id` in the real schema for the Shopee user — rename in the test above to avoid confusion. **If** the existing `nick_lives.user_id` column conflict arises: rename the Shopee field. Check first: `grep -n "user_id" backend/app/models/nick_live.py`. If it conflicts, rename the Shopee column to `shopee_user_id` as part of this task and update all usages (`backend/app/services/*.py`, `backend/app/routers/nick_live.py`, `backend/app/schemas/nick_live.py`).

- [ ] **Step 6: Handle nick_lives.user_id naming conflict**

Since the existing `NickLive` model already has `user_id: BigInteger` (Shopee user id), we MUST rename that field before adding the auth FK.

In `backend/app/models/nick_live.py`:

```python
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.crypto import EncryptedString


class NickLive(Base):
    __tablename__ = "nick_lives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    shopee_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shop_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cookies: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
```

Run to find all references to `user_id` in nick_live contexts:

```bash
grep -rn "\.user_id" backend/app/services backend/app/routers backend/app/schemas | grep -v "user_id.*current"
```

For each reference that refers to the **Shopee** user id on a `NickLive` object (e.g., `nick.user_id` passed to Shopee API calls), rename to `nick.shopee_user_id`. Specifically check:
- `backend/app/schemas/nick_live.py` — rename field
- `backend/app/routers/nick_live.py` — rename usages
- `backend/app/services/shopee_api.py` — param names
- `backend/app/services/relive_service.py` — if referenced

Extend migration 004 to rename the SQLite column:

```python
# In migrate() before adding new user_id:
if _col_exists(cur, "nick_lives", "user_id") and not _col_exists(cur, "nick_lives", "shopee_user_id"):
    # Existing column is the Shopee user id; rename it.
    cur.execute("ALTER TABLE nick_lives RENAME COLUMN user_id TO shopee_user_id")
    logger.info("Renamed nick_lives.user_id -> shopee_user_id")
```

Place this block **before** the `if not _col_exists(cur, "nick_lives", "user_id"):` block so the rename happens first, then the auth user_id column is added fresh.

- [ ] **Step 7: Run migration test**

Run: `cd backend && pytest tests/test_migration_004.py -v`
Expected: PASS.

- [ ] **Step 8: Smoke-run existing suite**

Run: `cd backend && pytest -x`
Expected: all existing tests still pass (may need to update fixtures that mention `user_id` on nick objects to `shopee_user_id`).

- [ ] **Step 9: Commit**

```bash
rtk git add backend/app/models/nick_live.py backend/app/models/settings.py backend/app/database.py backend/migrations/004_multi_user.py backend/tests/test_migration_004.py backend/app/schemas/nick_live.py backend/app/routers/nick_live.py backend/app/services/shopee_api.py backend/app/services/relive_service.py
rtk git commit -m "feat(auth): users table migration + rename nick_lives.user_id to shopee_user_id"
```

---

### Task 7: `get_current_user` dependency

**Files:**
- Modify: `backend/app/dependencies.py`
- Test: `backend/tests/test_dependencies_auth.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_dependencies_auth.py`:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.dependencies import get_current_user
from app.models.user import User
from app.services.auth import create_access_token, hash_password


@pytest.fixture(autouse=True)
def _db():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(User).delete()
        db.commit()
    yield


def _seed_user(**overrides):
    with SessionLocal() as db:
        u = User(
            username=overrides.get("username", "alice"),
            password_hash=hash_password("pw12345678"),
            role=overrides.get("role", "user"),
            max_nicks=overrides.get("max_nicks", 5),
            is_locked=overrides.get("is_locked", False),
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        return u.id


def _app():
    app = FastAPI()

    @app.get("/me")
    def me(user=pytest.importorskip("fastapi").Depends(get_current_user)):
        return {"id": user.id, "username": user.username}

    return app


def test_missing_token_401():
    client = TestClient(_app())
    r = client.get("/me")
    assert r.status_code == 401


def test_invalid_token_401():
    client = TestClient(_app())
    r = client.get("/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


def test_valid_token_returns_user():
    uid = _seed_user()
    token = create_access_token(user_id=uid, username="alice", role="user")
    client = TestClient(_app())
    r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["username"] == "alice"


def test_locked_user_403():
    uid = _seed_user(is_locked=True)
    token = create_access_token(user_id=uid, username="alice", role="user")
    client = TestClient(_app())
    r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_query_token_works_for_sse():
    uid = _seed_user()
    token = create_access_token(user_id=uid, username="alice", role="user")
    client = TestClient(_app())
    r = client.get(f"/me?token={token}")
    assert r.status_code == 200
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd backend && pytest tests/test_dependencies_auth.py -v`
Expected: import/usage error.

- [ ] **Step 3: Implement**

Rewrite `backend/app/dependencies.py`:

```python
from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.auth import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def _extract_token(
    request: Request,
    creds: HTTPAuthorizationCredentials | None,
    query_token: str | None,
) -> str | None:
    if creds and creds.scheme.lower() == "bearer":
        return creds.credentials
    if query_token:
        return query_token
    return None


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: str | None = Query(None),
    db: Session = Depends(get_db),
) -> User:
    raw = _extract_token(request, creds, token)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing auth token")
    payload = decode_access_token(raw)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Malformed token")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    if user.is_locked:
        raise HTTPException(status_code=403, detail="Account is locked")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user
```

- [ ] **Step 4: Run — expect PASS**

Run: `cd backend && pytest tests/test_dependencies_auth.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add backend/app/dependencies.py backend/tests/test_dependencies_auth.py
rtk git commit -m "feat(auth): get_current_user + require_admin deps"
```

---

### Task 8: Login, /me, change-password endpoints

**Files:**
- Create: `backend/app/schemas/user.py`
- Create: `backend/app/routers/auth.py`
- Modify: `backend/app/main.py` (include router)
- Test: `backend/tests/test_auth_router.py`

- [ ] **Step 1: Create schemas**

Create `backend/app/schemas/user.py`:

```python
from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=1)


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    max_nicks: int | None
    is_locked: bool
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


class UserUpdate(BaseModel):
    max_nicks: int | None = Field(default=None, ge=0)
    is_locked: bool | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=100)
```

- [ ] **Step 2: Write failing tests**

Create `backend/tests/test_auth_router.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.user import User
from app.services.auth import hash_password


@pytest.fixture(autouse=True)
def _db():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(User).delete()
        db.add(User(username="alice", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=3))
        db.add(User(username="locked", password_hash=hash_password("pw12345678"),
                    role="user", is_locked=True))
        db.commit()
    yield


client = TestClient(app)


def test_login_success():
    r = client.post("/api/auth/login",
                    json={"username": "alice", "password": "pw12345678"})
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert data["user"]["username"] == "alice"


def test_login_wrong_password():
    r = client.post("/api/auth/login",
                    json={"username": "alice", "password": "bad"})
    assert r.status_code == 401


def test_login_locked_account():
    r = client.post("/api/auth/login",
                    json={"username": "locked", "password": "pw12345678"})
    assert r.status_code == 403


def test_login_unknown_user():
    r = client.post("/api/auth/login",
                    json={"username": "nobody", "password": "pw12345678"})
    assert r.status_code == 401


def _token(username="alice", password="pw12345678"):
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    return r.json()["access_token"]


def test_me():
    tok = _token()
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["username"] == "alice"


def test_change_password_success():
    tok = _token()
    r = client.post("/api/auth/change-password",
                    headers={"Authorization": f"Bearer {tok}"},
                    json={"old_password": "pw12345678", "new_password": "newpw12345"})
    assert r.status_code == 204

    # new password works
    r2 = client.post("/api/auth/login",
                     json={"username": "alice", "password": "newpw12345"})
    assert r2.status_code == 200
    # old fails
    r3 = client.post("/api/auth/login",
                     json={"username": "alice", "password": "pw12345678"})
    assert r3.status_code == 401


def test_change_password_wrong_old():
    tok = _token()
    r = client.post("/api/auth/change-password",
                    headers={"Authorization": f"Bearer {tok}"},
                    json={"old_password": "bad", "new_password": "newpw12345"})
    assert r.status_code == 400


def test_change_password_too_short():
    tok = _token()
    r = client.post("/api/auth/change-password",
                    headers={"Authorization": f"Bearer {tok}"},
                    json={"old_password": "pw12345678", "new_password": "short"})
    assert r.status_code == 422
```

- [ ] **Step 3: Implement router**

Create `backend/app/routers/auth.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.user import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    UserOut,
)
from app.services.auth import (
    create_access_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.is_locked:
        raise HTTPException(status_code=403, detail="Account is locked")
    token = create_access_token(
        user_id=user.id, username=user.username, role=user.role
    )
    return LoginResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.post("/change-password", status_code=204)
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Old password incorrect")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return Response(status_code=204)
```

- [ ] **Step 4: Register router in `main.py`**

In `backend/app/main.py`, add import and include:

```python
from app.routers.auth import router as auth_router
# ...
app.include_router(auth_router)
```

- [ ] **Step 5: Run tests — expect PASS**

Run: `cd backend && pytest tests/test_auth_router.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add backend/app/schemas/user.py backend/app/routers/auth.py backend/app/main.py backend/tests/test_auth_router.py
rtk git commit -m "feat(auth): login, me, change-password endpoints"
```

---

### Task 9: Admin users CRUD

**Files:**
- Create: `backend/app/routers/admin.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_admin_router.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_admin_router.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.user import User
from app.services.auth import hash_password


@pytest.fixture(autouse=True)
def _db():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(User).delete()
        db.add(User(username="admin", password_hash=hash_password("pw12345678"),
                    role="admin", max_nicks=None))
        db.add(User(username="alice", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=3))
        db.commit()
    yield


client = TestClient(app)


def _login(username, password="pw12345678"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    return r.json()["access_token"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_non_admin_forbidden():
    tok = _login("alice")
    r = client.get("/api/admin/users", headers=_hdr(tok))
    assert r.status_code == 403


def test_list_users_includes_nick_count():
    tok = _login("admin")
    r = client.get("/api/admin/users", headers=_hdr(tok))
    assert r.status_code == 200
    rows = r.json()
    assert any(u["username"] == "alice" and u["nick_count"] == 0 for u in rows)


def test_create_user():
    tok = _login("admin")
    r = client.post("/api/admin/users", headers=_hdr(tok),
                    json={"username": "bob", "password": "pw12345678", "max_nicks": 5})
    assert r.status_code == 201
    assert r.json()["username"] == "bob"

    # Bob can login
    r2 = client.post("/api/auth/login",
                     json={"username": "bob", "password": "pw12345678"})
    assert r2.status_code == 200


def test_create_duplicate_rejected():
    tok = _login("admin")
    r = client.post("/api/admin/users", headers=_hdr(tok),
                    json={"username": "alice", "password": "pw12345678", "max_nicks": 5})
    assert r.status_code == 409


def test_update_max_nicks():
    tok = _login("admin")
    with SessionLocal() as db:
        alice_id = db.query(User).filter_by(username="alice").first().id
    r = client.patch(f"/api/admin/users/{alice_id}",
                     headers=_hdr(tok), json={"max_nicks": 10})
    assert r.status_code == 200
    assert r.json()["max_nicks"] == 10


def test_lock_unlock():
    tok = _login("admin")
    with SessionLocal() as db:
        alice_id = db.query(User).filter_by(username="alice").first().id
    client.patch(f"/api/admin/users/{alice_id}",
                 headers=_hdr(tok), json={"is_locked": True})
    # Alice can't login
    r = client.post("/api/auth/login",
                    json={"username": "alice", "password": "pw12345678"})
    assert r.status_code == 403
    # Unlock
    client.patch(f"/api/admin/users/{alice_id}",
                 headers=_hdr(tok), json={"is_locked": False})
    r2 = client.post("/api/auth/login",
                     json={"username": "alice", "password": "pw12345678"})
    assert r2.status_code == 200


def test_reset_password():
    tok = _login("admin")
    with SessionLocal() as db:
        alice_id = db.query(User).filter_by(username="alice").first().id
    r = client.patch(f"/api/admin/users/{alice_id}",
                     headers=_hdr(tok), json={"new_password": "brandnew99"})
    assert r.status_code == 200
    r2 = client.post("/api/auth/login",
                     json={"username": "alice", "password": "brandnew99"})
    assert r2.status_code == 200


def test_delete_user():
    tok = _login("admin")
    with SessionLocal() as db:
        alice_id = db.query(User).filter_by(username="alice").first().id
    r = client.delete(f"/api/admin/users/{alice_id}", headers=_hdr(tok))
    assert r.status_code == 204

    r2 = client.post("/api/auth/login",
                     json={"username": "alice", "password": "pw12345678"})
    assert r2.status_code == 401


def test_cannot_delete_self():
    tok = _login("admin")
    with SessionLocal() as db:
        admin_id = db.query(User).filter_by(username="admin").first().id
    r = client.delete(f"/api/admin/users/{admin_id}", headers=_hdr(tok))
    assert r.status_code == 400


def test_cannot_delete_last_admin():
    # delete alice, then try to delete admin (now the only admin)
    tok = _login("admin")
    with SessionLocal() as db:
        alice_id = db.query(User).filter_by(username="alice").first().id
        admin_id = db.query(User).filter_by(username="admin").first().id
    client.delete(f"/api/admin/users/{alice_id}", headers=_hdr(tok))
    # Create a second admin for this test? No — admin is still the only admin.
    # The rule: can't delete last admin. Here admin is itself & also self => caught by self-check.
    r = client.delete(f"/api/admin/users/{admin_id}", headers=_hdr(tok))
    assert r.status_code == 400
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd backend && pytest tests/test_admin_router.py -v`

- [ ] **Step 3: Implement router**

Create `backend/app/routers/admin.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_admin
from app.models.nick_live import NickLive
from app.models.user import User
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.auth import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])


class UserWithCount(UserOut):
    nick_count: int


@router.get("/users", response_model=list[UserWithCount])
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
    return [
        UserWithCount(**UserOut.model_validate(u).model_dump(), nick_count=int(c))
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
    if not changed:
        raise HTTPException(status_code=400, detail="No fields to update")
    db.commit()
    db.refresh(u)

    # Side effect: on lock/unlock, stop/start user's auto-poster loops
    if body.is_locked is not None:
        from app.main import auto_poster
        if auto_poster is not None:
            if body.is_locked:
                auto_poster.stop_user_nicks(u.id)
            else:
                auto_poster.start_user_nicks(u.id)

    return UserOut.model_validate(u)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if u.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    if u.role == "admin":
        remaining = db.query(User).filter(User.role == "admin", User.id != u.id).count()
        if remaining == 0:
            raise HTTPException(status_code=400, detail="Cannot delete last admin")

    # Side effects: stop loops & drop cache before cascade delete.
    from app.main import auto_poster
    from app.services.live_moderator import moderator
    if auto_poster is not None:
        auto_poster.stop_user_nicks(u.id)
    moderator.drop_user(u.id)

    db.delete(u)
    db.commit()
    return Response(status_code=204)
```

- [ ] **Step 4: Register router in `main.py`**

Add:

```python
from app.routers.admin import router as admin_router
# ...
app.include_router(admin_router)
```

- [ ] **Step 5: Add stubs on auto_poster and moderator (real impl Task 11)**

In `backend/app/services/auto_poster.py`, add placeholder methods:

```python
def stop_user_nicks(self, user_id: int) -> None:
    """Stop all auto-post loops for nicks owned by user_id. Implemented in Task 11."""
    pass

def start_user_nicks(self, user_id: int) -> None:
    """Re-start auto-post loops for nicks owned by user_id."""
    pass
```

In `backend/app/services/live_moderator.py`, add:

```python
def drop_user(self, user_id: int) -> None:
    """Evict moderator cache entries for nicks owned by user_id. Implemented in Task 11."""
    pass
```

- [ ] **Step 6: Run tests — expect PASS**

Run: `cd backend && pytest tests/test_admin_router.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
rtk git add backend/app/routers/admin.py backend/app/main.py backend/app/services/auto_poster.py backend/app/services/live_moderator.py backend/tests/test_admin_router.py
rtk git commit -m "feat(auth): admin users CRUD endpoints"
```

---

### Task 10: Scope nick_live router to user + quota enforcement

**Files:**
- Modify: `backend/app/routers/nick_live.py`
- Test: `backend/tests/test_user_isolation.py`, `backend/tests/test_quota.py`

- [ ] **Step 1: Write isolation + quota tests**

Create `backend/tests/test_quota.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.nick_live import NickLive
from app.models.user import User
from app.services.auth import hash_password


@pytest.fixture(autouse=True)
def _db():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(NickLive).delete()
        db.query(User).delete()
        db.add(User(username="admin", password_hash=hash_password("pw12345678"),
                    role="admin", max_nicks=None))
        db.add(User(username="alice", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=2))
        db.commit()
    yield


client = TestClient(app)


def _login(u, p="pw12345678"):
    return client.post("/api/auth/login", json={"username": u, "password": p}).json()["access_token"]


def _post_nick(tok, name):
    return client.post(
        "/api/nick-lives",
        headers={"Authorization": f"Bearer {tok}"},
        json={"name": name, "shopee_user_id": 1, "cookies": "c"},
    )


def test_quota_allows_up_to_max():
    tok = _login("alice")
    assert _post_nick(tok, "n1").status_code in (200, 201)
    assert _post_nick(tok, "n2").status_code in (200, 201)
    r = _post_nick(tok, "n3")
    assert r.status_code == 403
    assert "quota" in r.json()["detail"].lower() or "limit" in r.json()["detail"].lower()


def test_admin_unlimited():
    tok = _login("admin")
    for i in range(5):
        assert _post_nick(tok, f"a{i}").status_code in (200, 201)
```

Create `backend/tests/test_user_isolation.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.nick_live import NickLive
from app.models.user import User
from app.services.auth import hash_password


@pytest.fixture(autouse=True)
def _db():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(NickLive).delete()
        db.query(User).delete()
        db.add(User(username="alice", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=5))
        db.add(User(username="bob", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=5))
        db.commit()
    yield


client = TestClient(app)


def _login(u, p="pw12345678"):
    return client.post("/api/auth/login", json={"username": u, "password": p}).json()["access_token"]


def test_alice_cannot_see_bobs_nicks():
    atok = _login("alice")
    btok = _login("bob")
    client.post("/api/nick-lives", headers={"Authorization": f"Bearer {btok}"},
                json={"name": "bob-nick", "shopee_user_id": 1, "cookies": "c"})
    r = client.get("/api/nick-lives", headers={"Authorization": f"Bearer {atok}"})
    assert r.status_code == 200
    assert all(n["name"] != "bob-nick" for n in r.json())
```

- [ ] **Step 2: Run — expect FAIL (no auth on router yet)**

Run: `cd backend && pytest tests/test_quota.py tests/test_user_isolation.py -v`

- [ ] **Step 3: Update `nick_live` router**

In `backend/app/routers/nick_live.py`:

1. Remove/replace `Depends(require_api_key)` on every endpoint with `Depends(get_current_user)`.
2. Add import at top:

```python
from app.dependencies import get_current_user
from app.models.user import User
```

3. For every query that reads or modifies `NickLive`, add `NickLive.user_id == current_user.id` filter:

```python
# List:
nicks = db.query(NickLive).filter(NickLive.user_id == current_user.id).all()

# Single fetch:
nick = db.query(NickLive).filter(
    NickLive.id == nick_id, NickLive.user_id == current_user.id
).first()
if not nick:
    raise HTTPException(status_code=404, detail="Not found")
```

4. On POST (create nick), before the insert add quota check:

```python
if current_user.max_nicks is not None:
    count = db.query(NickLive).filter(NickLive.user_id == current_user.id).count()
    if count >= current_user.max_nicks:
        raise HTTPException(
            status_code=403,
            detail=f"Nick quota exceeded (max {current_user.max_nicks})",
        )
new_nick = NickLive(user_id=current_user.id, ...)
```

5. All endpoints now accept `current_user: User = Depends(get_current_user)` as a parameter.

6. Update the schema in `backend/app/schemas/nick_live.py`: rename `user_id` → `shopee_user_id` to match the model change from Task 6.

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd backend && pytest tests/test_quota.py tests/test_user_isolation.py -v`
Expected: all PASS.

- [ ] **Step 5: Run whole suite**

Run: `cd backend && pytest -x`
Expected: all PASS (update fixtures that now need auth headers / user rows).

- [ ] **Step 6: Commit**

```bash
rtk git add backend/app/routers/nick_live.py backend/app/schemas/nick_live.py backend/tests/test_quota.py backend/tests/test_user_isolation.py
rtk git commit -m "feat(auth): scope nick_live router to user + enforce quota"
```

---

### Task 11: Scope settings, knowledge, reply_logs routers + implement auto_poster user ops

**Files:**
- Modify: `backend/app/routers/settings.py`, `backend/app/routers/knowledge.py`, `backend/app/routers/reply_logs.py`
- Modify: `backend/app/services/auto_poster.py`, `backend/app/services/live_moderator.py`
- Modify: `backend/app/services/settings_service.py` (if it reads app_settings without user_id)

- [ ] **Step 1: Settings router — per-user**

Replace `require_api_key` with `get_current_user` and filter all `AppSetting` queries by `AppSetting.user_id == current_user.id`. All upserts set `user_id=current_user.id`.

Read `backend/app/routers/settings.py` first, then rewrite each endpoint. Pattern for upsert:

```python
row = db.query(AppSetting).filter(
    AppSetting.user_id == current_user.id, AppSetting.key == key
).first()
if row:
    row.value = value
else:
    row = AppSetting(user_id=current_user.id, key=key, value=value)
    db.add(row)
db.commit()
```

Update `backend/app/services/settings_service.py` to accept `user_id` arg on all public functions and include it in queries.

- [ ] **Step 2: Knowledge router**

In `backend/app/routers/knowledge.py`, replace auth dep. Filter by nick ownership: for any endpoint that reads/writes `KnowledgeProduct` by `nick_live_id`, first verify the nick belongs to `current_user`:

```python
nick = db.query(NickLive).filter(
    NickLive.id == nick_live_id, NickLive.user_id == current_user.id
).first()
if not nick:
    raise HTTPException(status_code=404, detail="Nick not found")
# then proceed with KnowledgeProduct queries keyed by nick_live_id
```

- [ ] **Step 3: Reply_logs router**

Same pattern as knowledge — endpoints that filter by `nick_live_id` first verify ownership. Endpoints that list across all nicks:

```python
owned_ids = db.query(NickLive.id).filter(NickLive.user_id == current_user.id).subquery()
logs = db.query(ReplyLog).filter(ReplyLog.nick_live_id.in_(owned_ids)).all()
```

- [ ] **Step 4: Implement `auto_poster.stop_user_nicks`**

Read `backend/app/services/auto_poster.py` to understand internal state (likely `self._loops: dict[int, Task]` keyed by nick_live_id). Implement:

```python
def _user_nick_ids(self, user_id: int) -> list[int]:
    from app.database import SessionLocal
    from app.models.nick_live import NickLive
    with SessionLocal() as db:
        return [nid for (nid,) in db.query(NickLive.id).filter(
            NickLive.user_id == user_id
        ).all()]

def stop_user_nicks(self, user_id: int) -> None:
    for nid in self._user_nick_ids(user_id):
        self.stop(nid)  # use existing per-nick stop method — adapt to actual API

def start_user_nicks(self, user_id: int) -> None:
    for nid in self._user_nick_ids(user_id):
        self.start(nid)  # use existing per-nick start method
```

**Note:** exact stop/start method names depend on the current class — check `backend/app/services/auto_poster.py`. If only `stop_all()` exists, replicate its per-nick logic here.

- [ ] **Step 5: Implement `moderator.drop_user`**

In `backend/app/services/live_moderator.py`:

```python
def drop_user(self, user_id: int) -> None:
    from app.database import SessionLocal
    from app.models.nick_live import NickLive
    with SessionLocal() as db:
        ids = [nid for (nid,) in db.query(NickLive.id).filter(
            NickLive.user_id == user_id
        ).all()]
    for nid in ids:
        self._cache.pop(nid, None)  # adapt to actual cache attr name
```

Check actual cache attribute by reading the file; adjust.

- [ ] **Step 6: Write a lock-side-effect test**

Add to `backend/tests/test_admin_router.py`:

```python
def test_lock_stops_auto_poster(monkeypatch):
    calls = []

    class FakePoster:
        def stop_user_nicks(self, uid): calls.append(("stop", uid))
        def start_user_nicks(self, uid): calls.append(("start", uid))
        def stop_all(self): pass

    import app.main
    monkeypatch.setattr(app.main, "auto_poster", FakePoster())

    tok = _login("admin")
    with SessionLocal() as db:
        alice_id = db.query(User).filter_by(username="alice").first().id

    client.patch(f"/api/admin/users/{alice_id}",
                 headers=_hdr(tok), json={"is_locked": True})
    client.patch(f"/api/admin/users/{alice_id}",
                 headers=_hdr(tok), json={"is_locked": False})
    assert ("stop", alice_id) in calls
    assert ("start", alice_id) in calls
```

- [ ] **Step 7: Run full suite**

Run: `cd backend && pytest -x`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
rtk git add backend/app/routers/settings.py backend/app/routers/knowledge.py backend/app/routers/reply_logs.py backend/app/services/auto_poster.py backend/app/services/live_moderator.py backend/app/services/settings_service.py backend/tests/test_admin_router.py
rtk git commit -m "feat(auth): scope settings/knowledge/reply_logs to user + lock side effects"
```

---

### Task 12: Remove `require_api_key`, update `.env.example` + README

**Files:**
- Modify: `backend/app/dependencies.py`
- Modify: `backend/.env.example` (create if missing)
- Modify: `README.md` (or project root `README`)

- [ ] **Step 1: Confirm no more callers**

Run:

```bash
grep -rn "require_api_key" backend/
```

Expected: only the definition in `dependencies.py` (or none if already removed). If any router still uses it, migrate them now.

- [ ] **Step 2: Delete `require_api_key`**

In `backend/app/dependencies.py`, delete the `require_api_key` function and its module-level constants (`_api_key_header`, `_APP_API_KEY`, `APIKeyHeader` import).

- [ ] **Step 3: Update `.env.example`**

Find or create `.env.example` at project root (or `backend/.env.example`). Add:

```env
# --- Auth ---
JWT_SECRET=change-me-to-a-long-random-string
JWT_TTL_HOURS=8
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-me-on-first-login

# --- Removed: APP_API_KEY (replaced by JWT auth) ---
```

Remove any existing `APP_API_KEY=...` line.

- [ ] **Step 4: Update README**

Add a section "Authentication" explaining: JWT, admin seeded from env on first boot, admin creates users via UI, per-user quota. One paragraph.

- [ ] **Step 5: Smoke run**

Run: `cd backend && pytest -x`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add backend/app/dependencies.py backend/.env.example README.md
rtk git commit -m "chore(auth): remove APP_API_KEY, document JWT auth setup"
```

---

### Task 13: Frontend — AuthContext + API interceptor

**Files:**
- Create: `frontend/src/contexts/AuthContext.tsx`
- Create: `frontend/src/api/auth.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: Create `AuthContext`**

Create `frontend/src/contexts/AuthContext.tsx`:

```tsx
import { createContext, useContext, useEffect, useState, ReactNode } from "react";

export interface AuthUser {
  id: number;
  username: string;
  role: "admin" | "user";
  max_nicks: number | null;
  is_locked: boolean;
}

interface AuthState {
  token: string | null;
  user: AuthUser | null;
}

interface AuthContextValue extends AuthState {
  login: (token: string, user: AuthUser) => void;
  logout: () => void;
  setUser: (user: AuthUser) => void;
}

const STORAGE_KEY = "auth";
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ token: null, user: null });

  useEffect(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      try {
        setState(JSON.parse(raw));
      } catch {
        localStorage.removeItem(STORAGE_KEY);
      }
    }
  }, []);

  const login = (token: string, user: AuthUser) => {
    const next = { token, user };
    setState(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  };

  const logout = () => {
    setState({ token: null, user: null });
    localStorage.removeItem(STORAGE_KEY);
  };

  const setUser = (user: AuthUser) => {
    const next = { ...state, user };
    setState(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  };

  return (
    <AuthContext.Provider value={{ ...state, login, logout, setUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
```

- [ ] **Step 2: Rewrite API client**

Replace `frontend/src/api/client.ts`:

```ts
import axios from "axios";

const apiClient = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

apiClient.interceptors.request.use((config) => {
  const raw = localStorage.getItem("auth");
  if (raw) {
    try {
      const { token } = JSON.parse(raw);
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    } catch {
      /* ignore */
    }
  }
  return config;
});

apiClient.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401 || error.response?.status === 403) {
      // Only redirect on auth endpoints / protected areas
      const url = error.config?.url ?? "";
      if (!url.includes("/auth/login")) {
        localStorage.removeItem("auth");
        if (window.location.pathname !== "/login") {
          window.location.href = "/login";
        }
      }
    }
    return Promise.reject(error);
  },
);

export function withTokenQuery(url: string): string {
  const raw = localStorage.getItem("auth");
  if (!raw) return url;
  try {
    const { token } = JSON.parse(raw);
    if (!token) return url;
    const sep = url.includes("?") ? "&" : "?";
    return `${url}${sep}token=${encodeURIComponent(token)}`;
  } catch {
    return url;
  }
}

export default apiClient;
```

- [ ] **Step 3: Create auth API calls**

Create `frontend/src/api/auth.ts`:

```ts
import apiClient from "./client";
import type { AuthUser } from "../contexts/AuthContext";

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const { data } = await apiClient.post<LoginResponse>("/auth/login", { username, password });
  return data;
}

export async function me(): Promise<AuthUser> {
  const { data } = await apiClient.get<AuthUser>("/auth/me");
  return data;
}

export async function changePassword(old_password: string, new_password: string): Promise<void> {
  await apiClient.post("/auth/change-password", { old_password, new_password });
}
```

- [ ] **Step 4: Wrap app in `AuthProvider`**

In `frontend/src/main.tsx`, wrap:

```tsx
import { AuthProvider } from "./contexts/AuthContext";
// ...
<AuthProvider>
  <BrowserRouter>
    <App />
  </BrowserRouter>
</AuthProvider>
```

(Wrap whatever `<App/>` is already wrapped in — keep existing providers.)

- [ ] **Step 5: Update any SSE URLs**

Run: `grep -rn "EventSource\|/api/.*stream" frontend/src`
For each EventSource URL, wrap with `withTokenQuery(...)` from `client.ts`.

- [ ] **Step 6: Commit**

```bash
rtk git add frontend/src/contexts/AuthContext.tsx frontend/src/api/client.ts frontend/src/api/auth.ts frontend/src/main.tsx
rtk git commit -m "feat(fe-auth): AuthContext + JWT-aware api client"
```

---

### Task 14: Frontend — Login page + ProtectedRoute + routing

**Files:**
- Create: `frontend/src/pages/Login.tsx`
- Create: `frontend/src/components/ProtectedRoute.tsx`
- Create: `frontend/src/components/AdminRoute.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Create Login page**

Create `frontend/src/pages/Login.tsx`:

```tsx
import { Form, Input, Button, Card, Alert } from "antd";
import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { login as loginApi } from "../api/auth";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: { username: string; password: string }) => {
    setError(null);
    setLoading(true);
    try {
      const res = await loginApi(values.username, values.password);
      login(res.access_token, res.user);
      const to = (location.state as { from?: string } | null)?.from ?? "/";
      navigate(to, { replace: true });
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } };
      if (err.response?.status === 403) {
        setError("Tài khoản đã bị khóa");
      } else if (err.response?.status === 401) {
        setError("Sai tài khoản hoặc mật khẩu");
      } else {
        setError(err.response?.data?.detail ?? "Đăng nhập thất bại");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center",
                  minHeight: "100vh", background: "#f0f2f5" }}>
      <Card title="Đăng nhập" style={{ width: 380 }}>
        {error && <Alert type="error" message={error} style={{ marginBottom: 16 }} />}
        <Form layout="vertical" onFinish={onFinish} disabled={loading}>
          <Form.Item label="Tên đăng nhập" name="username"
                     rules={[{ required: true, message: "Bắt buộc" }]}>
            <Input autoFocus />
          </Form.Item>
          <Form.Item label="Mật khẩu" name="password"
                     rules={[{ required: true, message: "Bắt buộc" }]}>
            <Input.Password />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            Đăng nhập
          </Button>
        </Form>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Create ProtectedRoute**

Create `frontend/src/components/ProtectedRoute.tsx`:

```tsx
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

export default function ProtectedRoute() {
  const { token } = useAuth();
  const location = useLocation();
  if (!token) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}
```

- [ ] **Step 3: Create AdminRoute**

Create `frontend/src/components/AdminRoute.tsx`:

```tsx
import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

export default function AdminRoute() {
  const { user } = useAuth();
  if (!user || user.role !== "admin") return <Navigate to="/" replace />;
  return <Outlet />;
}
```

- [ ] **Step 4: Rewire `App.tsx`**

Replace `frontend/src/App.tsx`:

```tsx
import { Routes, Route } from "react-router-dom";
import AppLayout from "./components/Layout";
import ProtectedRoute from "./components/ProtectedRoute";
import AdminRoute from "./components/AdminRoute";
import Login from "./pages/Login";
import Home from "./pages/Home";
import LiveScan from "./pages/LiveScan";
import Settings from "./pages/Settings";
import ChangePassword from "./pages/ChangePassword";
import AdminUsers from "./pages/AdminUsers";

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Home />} />
          <Route path="/live-scan" element={<LiveScan />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/change-password" element={<ChangePassword />} />
          <Route element={<AdminRoute />}>
            <Route path="/admin/users" element={<AdminUsers />} />
          </Route>
        </Route>
      </Route>
    </Routes>
  );
}

export default App;
```

- [ ] **Step 5: Run frontend dev**

Run: `cd frontend && npm run dev`
Manual check: unauthenticated → redirects to `/login`. Login with seeded admin → lands on `/`.

- [ ] **Step 6: Commit**

```bash
rtk git add frontend/src/pages/Login.tsx frontend/src/components/ProtectedRoute.tsx frontend/src/components/AdminRoute.tsx frontend/src/App.tsx
rtk git commit -m "feat(fe-auth): login page, protected routes, admin gate"
```

---

### Task 15: Frontend — ChangePassword page + header user dropdown

**Files:**
- Create: `frontend/src/pages/ChangePassword.tsx`
- Modify: `frontend/src/components/Layout.tsx` (inspect first)

- [ ] **Step 1: Read current Layout**

Run: `cat frontend/src/components/Layout.tsx` to see existing menu structure.

- [ ] **Step 2: Create ChangePassword page**

Create `frontend/src/pages/ChangePassword.tsx`:

```tsx
import { Form, Input, Button, Card, message } from "antd";
import { useState } from "react";
import { changePassword } from "../api/auth";

export default function ChangePasswordPage() {
  const [loading, setLoading] = useState(false);

  const onFinish = async (v: { old: string; next: string; confirm: string }) => {
    if (v.next !== v.confirm) {
      message.error("Mật khẩu xác nhận không khớp");
      return;
    }
    setLoading(true);
    try {
      await changePassword(v.old, v.next);
      message.success("Đổi mật khẩu thành công");
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail ?? "Đổi mật khẩu thất bại");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card title="Đổi mật khẩu" style={{ maxWidth: 480 }}>
      <Form layout="vertical" onFinish={onFinish}>
        <Form.Item label="Mật khẩu hiện tại" name="old" rules={[{ required: true }]}>
          <Input.Password />
        </Form.Item>
        <Form.Item label="Mật khẩu mới" name="next"
                   rules={[{ required: true, min: 8, message: "Tối thiểu 8 ký tự" }]}>
          <Input.Password />
        </Form.Item>
        <Form.Item label="Xác nhận mật khẩu mới" name="confirm"
                   rules={[{ required: true }]}>
          <Input.Password />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={loading}>Lưu</Button>
      </Form>
    </Card>
  );
}
```

- [ ] **Step 3: Add user dropdown to Layout**

In `frontend/src/components/Layout.tsx`, within the header area add an antd `Dropdown` with the current username:

```tsx
import { Dropdown, Avatar, Space } from "antd";
import { UserOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

// inside Layout component:
const { user, logout } = useAuth();
const navigate = useNavigate();

const menu = {
  items: [
    { key: "cp", label: "Đổi mật khẩu", onClick: () => navigate("/change-password") },
    ...(user?.role === "admin"
      ? [{ key: "admin", label: "Quản lý user", onClick: () => navigate("/admin/users") }]
      : []),
    { type: "divider" as const },
    { key: "logout", label: "Đăng xuất", onClick: () => { logout(); navigate("/login"); } },
  ],
};

// inside header JSX, render on the right:
<Dropdown menu={menu} placement="bottomRight">
  <Space style={{ cursor: "pointer" }}>
    <Avatar icon={<UserOutlined />} />
    <span>{user?.username}</span>
  </Space>
</Dropdown>
```

Integrate this into the existing Layout structure — the exact placement depends on the current JSX; place it in the right side of the header so existing nav stays intact.

- [ ] **Step 4: Manual check**

Login → header shows username → dropdown opens → Đổi mật khẩu works → Đăng xuất clears token and redirects to `/login`.

- [ ] **Step 5: Commit**

```bash
rtk git add frontend/src/pages/ChangePassword.tsx frontend/src/components/Layout.tsx
rtk git commit -m "feat(fe-auth): change password page + header user dropdown"
```

---

### Task 16: Frontend — Admin users management page

**Files:**
- Create: `frontend/src/api/admin.ts`
- Create: `frontend/src/pages/AdminUsers.tsx`

- [ ] **Step 1: Create admin API**

Create `frontend/src/api/admin.ts`:

```ts
import apiClient from "./client";

export interface AdminUser {
  id: number;
  username: string;
  role: "admin" | "user";
  max_nicks: number | null;
  is_locked: boolean;
  created_at: string;
  nick_count: number;
}

export async function listUsers(): Promise<AdminUser[]> {
  const { data } = await apiClient.get<AdminUser[]>("/admin/users");
  return data;
}

export async function createUser(body: {
  username: string; password: string; max_nicks: number | null;
}): Promise<AdminUser> {
  const { data } = await apiClient.post<AdminUser>("/admin/users", body);
  return data;
}

export async function updateUser(id: number, body: {
  max_nicks?: number | null; is_locked?: boolean; new_password?: string;
}): Promise<AdminUser> {
  const { data } = await apiClient.patch<AdminUser>(`/admin/users/${id}`, body);
  return data;
}

export async function deleteUser(id: number): Promise<void> {
  await apiClient.delete(`/admin/users/${id}`);
}
```

- [ ] **Step 2: Create AdminUsers page**

Create `frontend/src/pages/AdminUsers.tsx`:

```tsx
import { Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Space, Switch, Table, Tag, message } from "antd";
import { useEffect, useState } from "react";
import { AdminUser, createUser, deleteUser, listUsers, updateUser } from "../api/admin";

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

  useEffect(() => { refresh(); }, []);

  const handleCreate = async (v: { username: string; password: string; max_nicks: number | null }) => {
    try {
      await createUser({ username: v.username, password: v.password,
                         max_nicks: v.max_nicks ?? null });
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
    await updateUser(u.id, { is_locked: !u.is_locked });
    refresh();
  };

  const handleQuota = async (u: AdminUser, value: number | null) => {
    await updateUser(u.id, { max_nicks: value });
    refresh();
  };

  const handleReset = async (v: { new_password: string }) => {
    if (!pwdModal) return;
    await updateUser(pwdModal.id, { new_password: v.new_password });
    message.success("Đã đặt lại mật khẩu");
    setPwdModal(null);
    pwdForm.resetFields();
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
          { title: "Role", dataIndex: "role",
            render: (r) => <Tag color={r === "admin" ? "gold" : "blue"}>{r}</Tag> },
          { title: "Nicks", render: (_, u) => `${u.nick_count} / ${u.max_nicks ?? "∞"}` },
          { title: "Max nicks", render: (_, u) => (
              <InputNumber min={0} value={u.max_nicks ?? undefined} placeholder="∞"
                onChange={(v) => handleQuota(u, v === undefined ? null : Number(v))} />
          )},
          { title: "Trạng thái", render: (_, u) => (
              <Switch checked={!u.is_locked} onChange={() => handleToggleLock(u)}
                      checkedChildren="Active" unCheckedChildren="Locked" />
          )},
          { title: "Hành động", render: (_, u) => (
              <Space>
                <Button size="small" onClick={() => setPwdModal(u)}>Reset MK</Button>
                <Popconfirm title={`Xóa user ${u.username}?`} onConfirm={() => handleDelete(u)}>
                  <Button size="small" danger>Xóa</Button>
                </Popconfirm>
              </Space>
          )},
        ]}
      />

      <Modal title="Tạo user mới" open={createOpen}
             onCancel={() => setCreateOpen(false)}
             onOk={() => createForm.submit()}>
        <Form form={createForm} layout="vertical" onFinish={handleCreate}>
          <Form.Item name="username" label="Username"
                     rules={[{ required: true, min: 3, max: 50,
                               pattern: /^[A-Za-z0-9_-]+$/,
                               message: "3-50 ký tự, chỉ a-z 0-9 _ -" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="password" label="Mật khẩu"
                     rules={[{ required: true, min: 8 }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="max_nicks" label="Giới hạn nick (để trống = không giới hạn)">
            <InputNumber min={0} style={{ width: "100%" }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={`Đặt lại mật khẩu: ${pwdModal?.username ?? ""}`}
             open={!!pwdModal}
             onCancel={() => setPwdModal(null)}
             onOk={() => pwdForm.submit()}>
        <Form form={pwdForm} layout="vertical" onFinish={handleReset}>
          <Form.Item name="new_password" label="Mật khẩu mới"
                     rules={[{ required: true, min: 8 }]}>
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
```

- [ ] **Step 3: Manual check**

Login as admin → `/admin/users`:
- Create user `bob` / `pw12345678` / max 3 → appears in table
- Logout → login as `bob` → works
- Back as admin → lock bob → bob cannot login
- Reset bob's password → new password works
- Delete bob → disappears

Non-admin navigating to `/admin/users` → redirected to `/`.

- [ ] **Step 4: Commit**

```bash
rtk git add frontend/src/api/admin.ts frontend/src/pages/AdminUsers.tsx
rtk git commit -m "feat(fe-auth): admin users management page"
```

---

### Task 17: Frontend — quota toast on nick create

**Files:**
- Modify: `frontend/src/pages/Home.tsx` (or wherever POST /nick-lives is called)

- [ ] **Step 1: Find the call site**

Run: `grep -rn "nick-lives\|createNick\|addNick" frontend/src` to find where nick is created.

- [ ] **Step 2: Wrap the POST call in try/catch**

At the call site, on error with status 403 whose detail mentions "quota", show an antd `message.error` with `"Đã đạt giới hạn ${user.max_nicks} nick của tài khoản"`. For all other 403 detail strings, show the raw detail.

Example:

```tsx
try {
  await apiClient.post("/nick-lives", body);
} catch (e: unknown) {
  const err = e as { response?: { status?: number; data?: { detail?: string } } };
  if (err.response?.status === 403) {
    message.error(err.response.data?.detail ?? "Không được phép");
  } else {
    message.error("Thêm nick thất bại");
  }
  return;
}
```

- [ ] **Step 3: Commit**

```bash
rtk git add frontend/src/pages/Home.tsx
rtk git commit -m "feat(fe-auth): show quota message on nick create 403"
```

---

### Task 18: End-to-end smoke verification

**Files:** none.

- [ ] **Step 1: Start backend**

```bash
cd backend
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=adminpw123
export JWT_SECRET=smoke-test-secret
python run.py
```

- [ ] **Step 2: Start frontend**

```bash
cd frontend
npm run dev
```

- [ ] **Step 3: Manual E2E checklist**

Walk through:
- Visit `http://localhost:5173/` → redirected to `/login`.
- Login `admin` / `adminpw123` → lands on `/`.
- `/admin/users` → create user `bob` / `pw12345678` / max 2.
- Logout → login `bob`.
- Add 2 nicks → ok. Add 3rd → quota error toast.
- `/settings` → set Relive + AI config for bob. Logout.
- Login admin → `/settings` → bob's config is NOT visible (admin has own settings).
- Admin locks bob → bob can't login (403 error on login page).
- Admin unlocks bob → bob logs in again, 2 nicks still there.
- Admin deletes bob → login fails ("invalid credentials").

- [ ] **Step 4: Run full backend suite**

Run: `cd backend && pytest --cov=app --cov-report=term-missing`
Expected: coverage ≥ 80% on new modules; all tests pass.

- [ ] **Step 5: Commit (if any fixup made)**

Create a commit if any fixes were needed. Otherwise continue.

---

## Self-Review

1. **Spec coverage:**
   - Data model (users table, user_id on nick_lives + app_settings) → Task 3, 6. ✓
   - Seed admin from env → Task 6. ✓
   - JWT (header + query for SSE) → Task 4, 5, 7, 13. ✓
   - Login / me / change-password → Task 8. ✓
   - Admin CRUD — create, list+nick_count, patch max_nicks/lock/reset, delete with last-admin/self-guards → Task 9. ✓
   - Scope nick_live + quota enforcement → Task 10. ✓
   - Scope settings/knowledge/reply_logs → Task 11. ✓
   - Lock/delete side effects on auto_poster + moderator → Task 9 (wiring) + Task 11 (impl). ✓
   - Remove APP_API_KEY + .env.example + README → Task 12. ✓
   - Frontend: AuthContext, protected routes, login, change-password, admin users, quota toast, header dropdown → Tasks 13–17. ✓
   - E2E smoke → Task 18. ✓
   - Rate limit (5/15min per IP) → **not yet covered by a task**. Adding below.

2. **Placeholder scan:** No TBD/TODO.

3. **Type consistency:** `max_nicks: int | None`, `is_locked: bool`, `role: 'admin'|'user'` consistent across model, schema, FE types.

4. **Gap fix — add rate limit task below.**

---

### Task 19: Login rate limit (5 failed attempts / 15 min / IP)

**Files:**
- Modify: `backend/app/main.py` (init slowapi)
- Modify: `backend/app/routers/auth.py` (decorate login)
- Test: `backend/tests/test_rate_limit.py`

- [ ] **Step 1: Init limiter**

In `backend/app/main.py` add near the top after `app = FastAPI(...)`:

```python
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from fastapi.responses import JSONResponse

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

@app.exception_handler(RateLimitExceeded)
def _rl_handler(request, exc):
    return JSONResponse(status_code=429, content={"detail": "Too many attempts, try again later"})
```

- [ ] **Step 2: Decorate login**

In `backend/app/routers/auth.py`, add:

```python
from fastapi import Request
from app.main import limiter  # or import lazily to avoid cycle — see note

@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/15minutes")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    ...
```

**Note on circular import:** if `app.main` imports `auth.router` and `auth.router` imports `app.main.limiter`, circularity will break. Instead, create `backend/app/rate_limit.py` with just `limiter = Limiter(...)`, import it in both `main.py` and `auth.py`.

- [ ] **Step 3: Test**

Create `backend/tests/test_rate_limit.py`:

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_login_rate_limited():
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "x", "password": "y"})
    r = client.post("/api/auth/login", json={"username": "x", "password": "y"})
    assert r.status_code == 429
```

- [ ] **Step 4: Run**

Run: `cd backend && pytest tests/test_rate_limit.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add backend/app/rate_limit.py backend/app/main.py backend/app/routers/auth.py backend/tests/test_rate_limit.py
rtk git commit -m "feat(auth): rate limit login 5/15min per IP"
```
