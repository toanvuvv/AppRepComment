# Seeding Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-user proxy management to Seeding — bulk import (`host:port:user:pass`), CRUD, round-robin assignment to clones, and actually use the proxy when sending Shopee type-100 comments.

**Architecture:** New `seeding_proxies` table (per-user pool). `SeedingClone.proxy_id` FK + `SeedingClone.proxy` cached URL string. Sender resolves clone → proxy URL → per-proxy cached `httpx.AsyncClient`. UI: single modal under Seeding ▸ Clones tab.

**Tech Stack:** FastAPI, SQLAlchemy 2.x ORM, SQLite (custom migration scripts in `backend/migrations/NNN_*.py`), httpx, pytest. Frontend: React + Ant Design + Axios, custom hooks (no React Query).

**Reference spec:** `docs/superpowers/specs/2026-04-27-seeding-proxy-design.md`

---

## File Structure

**New backend files:**
- `backend/migrations/011_seeding_proxies.py` — DDL: create `seeding_proxies`, add `proxy_id` to `seeding_clones`.
- `backend/app/schemas/seeding_proxy.py` — Pydantic schemas.
- `backend/app/services/seeding_proxy_service.py` — parsing, import, format_url, assign, cache refresh.
- `backend/app/routers/seeding_proxy.py` — REST endpoints.
- `backend/tests/test_seeding_proxy_service.py`
- `backend/tests/test_seeding_proxy_router.py`

**Modified backend files:**
- `backend/app/models/seeding.py` — add `SeedingProxy`; add `proxy_id` column to `SeedingClone`.
- `backend/app/database.py` — register migration 011.
- `backend/app/services/http_client.py` — add `get_client_for_proxy(proxy_url)`.
- `backend/app/services/seeding_sender.py` — wire proxy URL into request, enforce `require_proxy`.
- `backend/app/routers/seeding.py` — extend `SeedingCloneResponse` payload with `proxy_meta`; mount proxy router.
- `backend/app/main.py` — register `seeding_proxy.router`.
- `backend/app/schemas/seeding.py` — extend `SeedingCloneResponse` with optional `proxy_meta`.
- `backend/tests/test_seeding_sender.py` — add proxy-path tests.

**New frontend files:**
- `frontend/src/api/seedingProxy.ts` — API client + types.
- `frontend/src/hooks/useSeedingProxies.ts` — fetch/CRUD hook (mirror of `useSeedingClones`).
- `frontend/src/components/seeding/ProxyImportPanel.tsx`
- `frontend/src/components/seeding/ProxyTable.tsx`
- `frontend/src/components/seeding/ProxySettingsModal.tsx`

**Modified frontend files:**
- `frontend/src/api/seeding.ts` — extend `SeedingClone` with `proxy_meta?`.
- `frontend/src/components/seeding/ClonesTab.tsx` — add "Setting Proxy" button; render `proxy_meta` in Proxy column instead of free-text input.

---

## Task 1: Migration 011 — schema changes

**Files:**
- Create: `backend/migrations/011_seeding_proxies.py`
- Modify: `backend/app/database.py:200-202`

- [ ] **Step 1: Write the migration script**

Create `backend/migrations/011_seeding_proxies.py`:

```python
"""Create seeding_proxies table and add seeding_clones.proxy_id.

Idempotent.
"""

import logging
import sqlite3

from app.database import engine

logger = logging.getLogger(__name__)


def _col_exists(cur: sqlite3.Cursor, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def _table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def migrate() -> None:
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        if not _table_exists(cur, "seeding_proxies"):
            cur.execute(
                """
                CREATE TABLE seeding_proxies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL
                        REFERENCES users(id) ON DELETE CASCADE,
                    scheme VARCHAR(10) NOT NULL,
                    host VARCHAR(255) NOT NULL,
                    port INTEGER NOT NULL,
                    username VARCHAR(255),
                    password TEXT,
                    note VARCHAR(255),
                    created_at DATETIME NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX ix_seeding_proxies_user_id "
                "ON seeding_proxies(user_id)"
            )
            cur.execute(
                "CREATE UNIQUE INDEX ux_seeding_proxies_unique "
                "ON seeding_proxies(user_id, scheme, host, port, "
                "COALESCE(username, ''))"
            )
            logger.info("Created seeding_proxies table")

        if not _col_exists(cur, "seeding_clones", "proxy_id"):
            cur.execute(
                "ALTER TABLE seeding_clones ADD COLUMN proxy_id INTEGER "
                "REFERENCES seeding_proxies(id) ON DELETE SET NULL"
            )
            cur.execute(
                "CREATE INDEX ix_seeding_clones_proxy_id "
                "ON seeding_clones(proxy_id)"
            )
            logger.info("Added seeding_clones.proxy_id")

        raw.commit()
        logger.info("Migration 011_seeding_proxies complete")
    finally:
        raw.close()
```

- [ ] **Step 2: Register migration in `init_db()`**

In `backend/app/database.py`, after the `m010 = ...; m010.migrate()` block (around line 200), add:

```python
    m011 = importlib.import_module("migrations.011_seeding_proxies")
    m011.migrate()
```

- [ ] **Step 3: Run app once to apply migration**

```bash
cd backend && python -c "from app.database import init_db; init_db()"
```

Expected: log line `Created seeding_proxies table` and `Added seeding_clones.proxy_id` (first run only). No errors. Re-running is a no-op.

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/011_seeding_proxies.py backend/app/database.py
git commit -m "feat(seeding): migration for seeding_proxies table and proxy_id FK"
```

---

## Task 2: SeedingProxy model + extend SeedingClone

**Files:**
- Modify: `backend/app/models/seeding.py`

- [ ] **Step 1: Add `SeedingProxy` class and `proxy_id` column**

At the end of `backend/app/models/seeding.py` (after `SeedingCommentTemplate`), add:

```python
class SeedingProxy(Base):
    __tablename__ = "seeding_proxies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    scheme: Mapped[str] = mapped_column(String(10), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False,
    )
```

In the existing `SeedingClone` class, after the `proxy:` field add:

```python
    proxy_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("seeding_proxies.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
```

- [ ] **Step 2: Register model in `init_db()` so `Base.metadata` knows it**

In `backend/app/database.py` `init_db()`, before `Base.metadata.create_all`, the seeding module is already imported transitively via routers. Add an explicit import for safety. Inside `init_db()` (near other `from app.models import ...`):

```python
    from app.models import seeding  # noqa: F401
```

- [ ] **Step 3: Smoke test — model loads + tables match**

```bash
cd backend && python -c "from app.models.seeding import SeedingProxy, SeedingClone; print(SeedingProxy.__tablename__, [c.name for c in SeedingProxy.__table__.columns]); print('proxy_id' in [c.name for c in SeedingClone.__table__.columns])"
```

Expected: `seeding_proxies ['id', 'user_id', 'scheme', 'host', 'port', 'username', 'password', 'note', 'created_at']` and `True`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/seeding.py backend/app/database.py
git commit -m "feat(seeding): SeedingProxy model + proxy_id on SeedingClone"
```

---

## Task 3: Pydantic schemas

**Files:**
- Create: `backend/app/schemas/seeding_proxy.py`

- [ ] **Step 1: Write all schema classes**

Create `backend/app/schemas/seeding_proxy.py`:

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ProxyScheme = Literal["socks5", "http", "https"]


class ProxyCreate(BaseModel):
    scheme: ProxyScheme
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=255)


class ProxyUpdate(BaseModel):
    scheme: ProxyScheme | None = None
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=255)


class ProxyOut(BaseModel):
    id: int
    scheme: ProxyScheme
    host: str
    port: int
    username: str | None
    note: str | None
    created_at: datetime
    used_by_count: int = 0
    model_config = {"from_attributes": True}


class ProxyImportRequest(BaseModel):
    scheme: ProxyScheme
    raw_text: str = Field(min_length=1, max_length=200_000)


class ProxyImportError(BaseModel):
    line: int
    raw: str
    reason: str


class ProxyImportResult(BaseModel):
    created: int
    skipped_duplicates: int
    errors: list[ProxyImportError]


class ProxyAssignRequest(BaseModel):
    only_unassigned: bool = False


class ProxyAssignResult(BaseModel):
    assigned: int
    reason: Literal["ok", "no_proxies", "no_clones", "all_assigned"]


class RequireProxySetting(BaseModel):
    require_proxy: bool
```

- [ ] **Step 2: Smoke test**

```bash
cd backend && python -c "from app.schemas.seeding_proxy import ProxyCreate, ProxyImportResult; p = ProxyCreate(scheme='socks5', host='x', port=1, username=None, password=None); print(p.model_dump())"
```

Expected: dict with all fields including `'username': None`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/seeding_proxy.py
git commit -m "feat(seeding): pydantic schemas for proxy CRUD/import/assign"
```

---

## Task 4: Service — `parse_bulk` (TDD)

**Files:**
- Create: `backend/app/services/seeding_proxy_service.py`
- Test: `backend/tests/test_seeding_proxy_service.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_seeding_proxy_service.py`:

```python
"""Unit tests for seeding_proxy_service (parse, import, assign, format_url)."""
import pytest

from app.services.seeding_proxy_service import (
    ParsedProxy,
    ParseError,
    parse_bulk,
)


def test_parse_bulk_valid_lines():
    raw = (
        "proxyx3.ddns.net:4001:proxy:proxy3\n"
        "1.2.3.4:8080:user1:pass1\n"
    )
    parsed, errors = parse_bulk(raw, "socks5")
    assert errors == []
    assert parsed == [
        ParsedProxy(scheme="socks5", host="proxyx3.ddns.net", port=4001,
                    username="proxy", password="proxy3"),
        ParsedProxy(scheme="socks5", host="1.2.3.4", port=8080,
                    username="user1", password="pass1"),
    ]


def test_parse_bulk_skips_blank_and_comment_lines():
    raw = "\n  \n# a comment\nproxyx3.ddns.net:4001:proxy:proxy3\n"
    parsed, errors = parse_bulk(raw, "http")
    assert errors == []
    assert len(parsed) == 1
    assert parsed[0].scheme == "http"


def test_parse_bulk_invalid_format_reports_error_keeps_others():
    raw = (
        "good.host:1234:u:p\n"
        "bad-line-no-colons\n"
        "another.host:80:u:p\n"
    )
    parsed, errors = parse_bulk(raw, "http")
    assert len(parsed) == 2
    assert len(errors) == 1
    assert errors[0].line == 2
    assert errors[0].raw == "bad-line-no-colons"
    assert errors[0].reason == "invalid_format"


def test_parse_bulk_invalid_port_reports_error():
    raw = "host.com:99999:u:p\n"
    parsed, errors = parse_bulk(raw, "http")
    assert parsed == []
    assert len(errors) == 1
    assert errors[0].reason == "invalid_port"


def test_parse_bulk_strips_whitespace():
    raw = "  host.com:80:u:p  \n"
    parsed, _ = parse_bulk(raw, "http")
    assert parsed[0].host == "host.com"
```

- [ ] **Step 2: Run tests, expect failure**

```bash
cd backend && pytest tests/test_seeding_proxy_service.py::test_parse_bulk_valid_lines -v
```

Expected: `ImportError` / module not found.

- [ ] **Step 3: Implement `parse_bulk`**

Create `backend/app/services/seeding_proxy_service.py`:

```python
"""Business logic for SeedingProxy: parse, import, assign, cache refresh."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote


ProxyScheme = Literal["socks5", "http", "https"]


@dataclass(frozen=True)
class ParsedProxy:
    scheme: ProxyScheme
    host: str
    port: int
    username: str | None
    password: str | None


@dataclass(frozen=True)
class ParseError:
    line: int
    raw: str
    reason: str


def parse_bulk(
    raw_text: str, scheme: ProxyScheme,
) -> tuple[list[ParsedProxy], list[ParseError]]:
    """Parse bulk proxy text. One proxy per line: ``host:port:user:pass``.

    Lines beginning with ``#`` and blank lines are skipped.
    """
    parsed: list[ParsedProxy] = []
    errors: list[ParseError] = []

    for idx, raw in enumerate(raw_text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":")
        if len(parts) != 4:
            errors.append(ParseError(idx, raw, "invalid_format"))
            continue
        host, port_raw, user, pwd = parts
        host = host.strip()
        if not host:
            errors.append(ParseError(idx, raw, "invalid_format"))
            continue
        try:
            port = int(port_raw)
        except ValueError:
            errors.append(ParseError(idx, raw, "invalid_port"))
            continue
        if not (1 <= port <= 65535):
            errors.append(ParseError(idx, raw, "invalid_port"))
            continue
        parsed.append(ParsedProxy(
            scheme=scheme, host=host, port=port,
            username=user or None, password=pwd or None,
        ))
    return parsed, errors
```

- [ ] **Step 4: Run tests, expect pass**

```bash
cd backend && pytest tests/test_seeding_proxy_service.py -k parse_bulk -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/seeding_proxy_service.py backend/tests/test_seeding_proxy_service.py
git commit -m "feat(seeding): parse_bulk for proxy import"
```

---

## Task 5: Service — `format_url` (TDD)

**Files:**
- Modify: `backend/app/services/seeding_proxy_service.py`
- Modify: `backend/tests/test_seeding_proxy_service.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_seeding_proxy_service.py`:

```python
from app.services.seeding_proxy_service import format_url


class _FakeProxy:
    def __init__(self, scheme, host, port, username=None, password=None):
        self.scheme = scheme
        self.host = host
        self.port = port
        self.username = username
        self.password = password


def test_format_url_with_auth():
    p = _FakeProxy("socks5", "proxyx3.ddns.net", 4001, "proxy", "proxy3")
    assert format_url(p) == "socks5://proxy:proxy3@proxyx3.ddns.net:4001"


def test_format_url_no_auth():
    p = _FakeProxy("http", "1.2.3.4", 8080)
    assert format_url(p) == "http://1.2.3.4:8080"


def test_format_url_url_encodes_password_with_special_chars():
    p = _FakeProxy("https", "h", 80, "user@x", "p@ss/word")
    assert format_url(p) == "https://user%40x:p%40ss%2Fword@h:80"
```

- [ ] **Step 2: Run tests, expect failure**

```bash
cd backend && pytest tests/test_seeding_proxy_service.py -k format_url -v
```

Expected: `ImportError: cannot import name 'format_url'`.

- [ ] **Step 3: Implement `format_url`**

Append to `backend/app/services/seeding_proxy_service.py`:

```python
def format_url(proxy) -> str:
    """Build the proxy URL string used by httpx.

    ``proxy`` may be a ``SeedingProxy`` ORM row or any object exposing
    ``scheme``, ``host``, ``port``, ``username``, ``password``.
    """
    if proxy.username:
        creds = f"{quote(proxy.username, safe='')}:{quote(proxy.password or '', safe='')}@"
    else:
        creds = ""
    return f"{proxy.scheme}://{creds}{proxy.host}:{proxy.port}"
```

- [ ] **Step 4: Run tests, expect pass**

```bash
cd backend && pytest tests/test_seeding_proxy_service.py -k format_url -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/seeding_proxy_service.py backend/tests/test_seeding_proxy_service.py
git commit -m "feat(seeding): format_url helper for proxy URL strings"
```

---

## Task 6: Service — `import_bulk` (TDD)

**Files:**
- Modify: `backend/app/services/seeding_proxy_service.py`
- Modify: `backend/tests/test_seeding_proxy_service.py`

- [ ] **Step 1: Write failing test (uses real DB session)**

Add to `backend/tests/test_seeding_proxy_service.py`:

```python
from app.database import Base, SessionLocal, engine, init_db
from app.models.seeding import SeedingProxy
from app.models.user import User
from app.services.seeding_proxy_service import import_bulk


@pytest.fixture
def db_user():
    init_db()
    with SessionLocal() as db:
        db.query(SeedingProxy).delete()
        db.query(User).filter(User.username == "proxytest").delete()
        u = User(username="proxytest", password_hash="x", role="user")
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
    yield uid
    with SessionLocal() as db:
        db.query(SeedingProxy).filter(SeedingProxy.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def test_import_bulk_creates_rows(db_user):
    raw = "h1.com:80:u:p\nh2.com:81:u:p\n"
    result = import_bulk(db_user, "http", raw)
    assert result.created == 2
    assert result.skipped_duplicates == 0
    assert result.errors == []
    with SessionLocal() as db:
        rows = db.query(SeedingProxy).filter(
            SeedingProxy.user_id == db_user
        ).all()
        assert len(rows) == 2


def test_import_bulk_dedupes_existing(db_user):
    raw1 = "h1.com:80:u:p\n"
    import_bulk(db_user, "http", raw1)
    raw2 = "h1.com:80:u:p\nh3.com:82:u:p\n"
    result = import_bulk(db_user, "http", raw2)
    assert result.created == 1
    assert result.skipped_duplicates == 1
    assert result.errors == []


def test_import_bulk_reports_parse_errors(db_user):
    raw = "h1.com:80:u:p\nbad-line\n"
    result = import_bulk(db_user, "http", raw)
    assert result.created == 1
    assert len(result.errors) == 1
    assert result.errors[0].reason == "invalid_format"
```

- [ ] **Step 2: Run tests, expect failure**

```bash
cd backend && pytest tests/test_seeding_proxy_service.py -k import_bulk -v
```

Expected: `ImportError: cannot import name 'import_bulk'`.

- [ ] **Step 3: Implement `import_bulk`**

Append to `backend/app/services/seeding_proxy_service.py`:

```python
from app.database import SessionLocal
from app.models.seeding import SeedingProxy
from app.schemas.seeding_proxy import ProxyImportError, ProxyImportResult


def import_bulk(
    user_id: int, scheme: ProxyScheme, raw_text: str,
) -> ProxyImportResult:
    """Insert parsed proxies, deduping against existing user rows."""
    parsed, parse_errors = parse_bulk(raw_text, scheme)
    errors = [
        ProxyImportError(line=e.line, raw=e.raw, reason=e.reason)
        for e in parse_errors
    ]

    if not parsed:
        return ProxyImportResult(
            created=0, skipped_duplicates=0, errors=errors,
        )

    created = 0
    skipped = 0
    with SessionLocal() as db:
        existing_rows = db.query(SeedingProxy).filter(
            SeedingProxy.user_id == user_id
        ).all()
        existing_keys = {
            (p.scheme, p.host, p.port, p.username or "")
            for p in existing_rows
        }
        for pp in parsed:
            key = (pp.scheme, pp.host, pp.port, pp.username or "")
            if key in existing_keys:
                skipped += 1
                continue
            db.add(SeedingProxy(
                user_id=user_id,
                scheme=pp.scheme, host=pp.host, port=pp.port,
                username=pp.username, password=pp.password,
            ))
            existing_keys.add(key)
            created += 1
        db.commit()

    return ProxyImportResult(
        created=created, skipped_duplicates=skipped, errors=errors,
    )
```

- [ ] **Step 4: Run tests, expect pass**

```bash
cd backend && pytest tests/test_seeding_proxy_service.py -k import_bulk -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/seeding_proxy_service.py backend/tests/test_seeding_proxy_service.py
git commit -m "feat(seeding): import_bulk with dedupe"
```

---

## Task 7: Service — `assign_round_robin` (TDD)

**Files:**
- Modify: `backend/app/services/seeding_proxy_service.py`
- Modify: `backend/tests/test_seeding_proxy_service.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_seeding_proxy_service.py`:

```python
from app.models.seeding import SeedingClone
from app.services.seeding_proxy_service import assign_round_robin


def _add_clone(db, user_id: int, name: str) -> SeedingClone:
    c = SeedingClone(
        user_id=user_id, name=name, shopee_user_id=1,
        cookies="x", proxy=None, proxy_id=None,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@pytest.fixture
def db_user_with_clones(db_user):
    with SessionLocal() as db:
        c1 = _add_clone(db, db_user, "C1")
        c2 = _add_clone(db, db_user, "C2")
        c3 = _add_clone(db, db_user, "C3")
        ids = [c1.id, c2.id, c3.id]
    yield db_user, ids
    with SessionLocal() as db:
        db.query(SeedingClone).filter(SeedingClone.user_id == db_user).delete()
        db.commit()


def test_assign_round_robin_2_proxies_3_clones(db_user_with_clones):
    user_id, clone_ids = db_user_with_clones
    import_bulk(user_id, "socks5", "h1:80:u:p\nh2:81:u:p\n")

    result = assign_round_robin(user_id, only_unassigned=False)
    assert result.assigned == 3
    assert result.reason == "ok"

    with SessionLocal() as db:
        clones = (db.query(SeedingClone)
                  .filter(SeedingClone.user_id == user_id)
                  .order_by(SeedingClone.id.asc()).all())
        proxies = (db.query(SeedingProxy)
                   .filter(SeedingProxy.user_id == user_id)
                   .order_by(SeedingProxy.id.asc()).all())
        assert clones[0].proxy_id == proxies[0].id
        assert clones[1].proxy_id == proxies[1].id
        assert clones[2].proxy_id == proxies[0].id  # wraps
        assert clones[0].proxy == "socks5://u:p@h1:80"
        assert clones[2].proxy == "socks5://u:p@h1:80"


def test_assign_round_robin_no_proxies(db_user_with_clones):
    user_id, _ = db_user_with_clones
    result = assign_round_robin(user_id, only_unassigned=False)
    assert result.assigned == 0
    assert result.reason == "no_proxies"


def test_assign_round_robin_no_clones(db_user):
    import_bulk(db_user, "http", "h1:80:u:p\n")
    result = assign_round_robin(db_user, only_unassigned=False)
    assert result.assigned == 0
    assert result.reason == "no_clones"


def test_assign_round_robin_only_unassigned_skips_assigned(db_user_with_clones):
    user_id, clone_ids = db_user_with_clones
    import_bulk(user_id, "http", "h1:80:u:p\n")
    # First call assigns all
    assign_round_robin(user_id, only_unassigned=False)

    # Add 1 more proxy and 1 more clone
    import_bulk(user_id, "http", "h2:81:u:p\n")
    with SessionLocal() as db:
        c4 = _add_clone(db, user_id, "C4")
        c4_id = c4.id

    result = assign_round_robin(user_id, only_unassigned=True)
    # Only c4 should be (re-)assigned
    assert result.assigned == 1
    with SessionLocal() as db:
        c4_row = db.get(SeedingClone, c4_id)
        # c4 gets the *first* of the 2 proxies (i=0 in unassigned set)
        assert c4_row.proxy_id is not None


def test_assign_round_robin_idempotent(db_user_with_clones):
    user_id, _ = db_user_with_clones
    import_bulk(user_id, "http", "h1:80:u:p\nh2:81:u:p\n")
    r1 = assign_round_robin(user_id, only_unassigned=False)
    r2 = assign_round_robin(user_id, only_unassigned=False)
    assert r1.assigned == r2.assigned == 3
```

- [ ] **Step 2: Run tests, expect failure**

```bash
cd backend && pytest tests/test_seeding_proxy_service.py -k assign_round_robin -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `assign_round_robin`**

Append to `backend/app/services/seeding_proxy_service.py`:

```python
from app.models.seeding import SeedingClone
from app.schemas.seeding_proxy import ProxyAssignResult


def assign_round_robin(user_id: int, only_unassigned: bool) -> ProxyAssignResult:
    """Round-robin assign proxies to clones (sorted by id ASC).

    With N proxies and M clones, ``clones[i].proxy_id = proxies[i mod N].id``.
    If ``only_unassigned`` is True, skip clones that already have a proxy.
    """
    with SessionLocal() as db:
        proxies = (
            db.query(SeedingProxy)
            .filter(SeedingProxy.user_id == user_id)
            .order_by(SeedingProxy.id.asc())
            .all()
        )
        if not proxies:
            return ProxyAssignResult(assigned=0, reason="no_proxies")

        q = (
            db.query(SeedingClone)
            .filter(SeedingClone.user_id == user_id)
        )
        if only_unassigned:
            q = q.filter(SeedingClone.proxy_id.is_(None))
        clones = q.order_by(SeedingClone.id.asc()).all()

        if not clones:
            # Differentiate "no clones at all" from "all already assigned"
            total = (
                db.query(SeedingClone)
                .filter(SeedingClone.user_id == user_id)
                .count()
            )
            if total == 0:
                return ProxyAssignResult(assigned=0, reason="no_clones")
            return ProxyAssignResult(assigned=0, reason="all_assigned")

        n = len(proxies)
        for i, clone in enumerate(clones):
            target = proxies[i % n]
            clone.proxy_id = target.id
            clone.proxy = format_url(target)
        db.commit()

        return ProxyAssignResult(assigned=len(clones), reason="ok")
```

- [ ] **Step 4: Run tests, expect pass**

```bash
cd backend && pytest tests/test_seeding_proxy_service.py -k assign_round_robin -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/seeding_proxy_service.py backend/tests/test_seeding_proxy_service.py
git commit -m "feat(seeding): assign_round_robin proxy → clones"
```

---

## Task 8: Service — cache refresh on edit/delete (TDD)

**Files:**
- Modify: `backend/app/services/seeding_proxy_service.py`
- Modify: `backend/tests/test_seeding_proxy_service.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_seeding_proxy_service.py`:

```python
from app.services.seeding_proxy_service import (
    refresh_clone_cache_for_proxy,
    clear_clone_cache_for_proxy,
)


def test_refresh_clone_cache_after_proxy_edit(db_user_with_clones):
    user_id, _ = db_user_with_clones
    import_bulk(user_id, "http", "h1:80:u:p\n")
    assign_round_robin(user_id, only_unassigned=False)

    with SessionLocal() as db:
        proxy = db.query(SeedingProxy).filter(
            SeedingProxy.user_id == user_id
        ).first()
        proxy.host = "newhost.com"
        db.commit()
        proxy_id = proxy.id

    refresh_clone_cache_for_proxy(proxy_id)

    with SessionLocal() as db:
        clones = db.query(SeedingClone).filter(
            SeedingClone.user_id == user_id
        ).all()
        for c in clones:
            assert c.proxy == "http://u:p@newhost.com:80"


def test_clear_clone_cache_after_proxy_delete(db_user_with_clones):
    user_id, _ = db_user_with_clones
    import_bulk(user_id, "http", "h1:80:u:p\n")
    assign_round_robin(user_id, only_unassigned=False)

    with SessionLocal() as db:
        proxy = db.query(SeedingProxy).filter(
            SeedingProxy.user_id == user_id
        ).first()
        proxy_id = proxy.id

    clear_clone_cache_for_proxy(proxy_id)

    with SessionLocal() as db:
        clones = db.query(SeedingClone).filter(
            SeedingClone.user_id == user_id
        ).all()
        for c in clones:
            assert c.proxy_id is None
            assert c.proxy is None
```

- [ ] **Step 2: Run tests, expect failure**

```bash
cd backend && pytest tests/test_seeding_proxy_service.py -k cache -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement helpers**

Append to `backend/app/services/seeding_proxy_service.py`:

```python
def refresh_clone_cache_for_proxy(proxy_id: int) -> None:
    """Refresh ``clone.proxy`` URL cache on every clone using this proxy."""
    with SessionLocal() as db:
        proxy = db.get(SeedingProxy, proxy_id)
        if proxy is None:
            return
        url = format_url(proxy)
        clones = db.query(SeedingClone).filter(
            SeedingClone.proxy_id == proxy_id
        ).all()
        for c in clones:
            c.proxy = url
        db.commit()


def clear_clone_cache_for_proxy(proxy_id: int) -> None:
    """Set ``proxy_id`` and ``proxy`` to NULL on clones using this proxy.

    Caller is expected to call this BEFORE deleting the proxy row so the
    explicit clear runs in the same transaction (FK ON DELETE SET NULL
    handles the column too, but we also clear the cached string).
    """
    with SessionLocal() as db:
        clones = db.query(SeedingClone).filter(
            SeedingClone.proxy_id == proxy_id
        ).all()
        for c in clones:
            c.proxy_id = None
            c.proxy = None
        db.commit()
```

- [ ] **Step 4: Run tests, expect pass**

```bash
cd backend && pytest tests/test_seeding_proxy_service.py -k cache -v
```

Expected: 2 passed.

- [ ] **Step 5: Run full service test file**

```bash
cd backend && pytest tests/test_seeding_proxy_service.py -v
```

Expected: all green (~13 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/seeding_proxy_service.py backend/tests/test_seeding_proxy_service.py
git commit -m "feat(seeding): clone proxy-cache refresh and clear helpers"
```

---

## Task 9: HTTP client — per-proxy cached AsyncClient

**Files:**
- Modify: `backend/app/services/http_client.py`

- [ ] **Step 1: Add `get_client_for_proxy` and an extended close**

Replace the contents of `backend/app/services/http_client.py` with:

```python
"""Lazy-initialized shared httpx.AsyncClient (direct + per-proxy).

FastAPI runs as a single event loop per worker process, so module-level
caches are safe. Clients are created on first use and closed on
application shutdown via ``close_client()``.
"""
from __future__ import annotations

import logging

import httpx

from app.config import HTTP_TIMEOUT_SEC

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_proxy_clients: dict[str, httpx.AsyncClient] = {}


def _build_client(proxy: str | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SEC,
        proxy=proxy,
        limits=httpx.Limits(
            max_connections=50,
            max_keepalive_connections=20,
        ),
    )


def get_client() -> httpx.AsyncClient:
    """Return the shared direct AsyncClient, creating it on first call."""
    global _client
    if _client is None:
        _client = _build_client(proxy=None)
        logger.info("Created shared httpx.AsyncClient (direct)")
    return _client


def get_client_for_proxy(proxy_url: str | None) -> httpx.AsyncClient:
    """Return a cached AsyncClient for the given proxy URL.

    ``None`` returns the shared direct client (same as ``get_client()``).
    Distinct proxy URLs each get their own client; clients are reused.
    """
    if not proxy_url:
        return get_client()
    client = _proxy_clients.get(proxy_url)
    if client is None:
        client = _build_client(proxy=proxy_url)
        _proxy_clients[proxy_url] = client
        logger.info("Created proxied httpx.AsyncClient for %s", proxy_url)
    return client


async def close_client() -> None:
    """Close the shared and all proxy clients; clear references."""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception as e:
            logger.warning(f"Error closing direct httpx client: {e}")
        finally:
            _client = None

    for url, client in list(_proxy_clients.items()):
        try:
            await client.aclose()
        except Exception as e:
            logger.warning(f"Error closing proxy client {url}: {e}")
    _proxy_clients.clear()
    logger.info("Closed all httpx.AsyncClients")
```

- [ ] **Step 2: Smoke test**

```bash
cd backend && python -c "import asyncio; from app.services.http_client import get_client_for_proxy, close_client; c1 = get_client_for_proxy('http://1.2.3.4:80'); c2 = get_client_for_proxy('http://1.2.3.4:80'); print(c1 is c2); asyncio.run(close_client())"
```

Expected: `True` (same client returned for same URL), no errors on close.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/http_client.py
git commit -m "feat(http): per-proxy cached AsyncClient via get_client_for_proxy"
```

---

## Task 10: Wire proxy into `seeding_sender` (TDD)

**Files:**
- Modify: `backend/app/services/seeding_sender.py`
- Modify: `backend/tests/test_seeding_sender.py`

- [ ] **Step 1: Write failing test for proxy wiring**

Append to `backend/tests/test_seeding_sender.py`:

```python
from unittest.mock import AsyncMock, patch

from app.services.seeding_sender import SeedingSender


@pytest.mark.asyncio
async def test_send_uses_proxied_client_when_clone_has_proxy():
    """Sender must acquire a client via get_client_for_proxy(clone.proxy)."""
    sender = SeedingSender()

    fake_clone = type("C", (), {
        "id": 99, "user_id": 1, "name": "C", "cookies": "x",
        "proxy": "socks5://u:p@h:80", "proxy_id": 5,
        "last_sent_at": None, "consecutive_failures": 0,
    })()

    fake_resp = type("R", (), {
        "status_code": 200, "json": lambda self: {"err_code": 0},
    })()

    with patch.object(
        sender, "_load_clone", new=AsyncMock(return_value=fake_clone),
    ), patch.object(
        sender, "_resolve_host_credentials",
        new=AsyncMock(return_value={"uuid": "u", "usersig": "s"}),
    ), patch.object(
        sender, "_touch_clone_last_sent", new=AsyncMock(),
    ), patch.object(
        sender, "_write_log", new=AsyncMock(return_value="log"),
    ), patch(
        "app.services.seeding_sender.get_client_for_proxy",
    ) as mock_factory, patch(
        "app.services.seeding_sender.shopee_limiter.acquire",
        new=AsyncMock(),
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=fake_resp)
        mock_factory.return_value = mock_client

        await sender.send(
            clone_id=99, nick_live_id=1, shopee_session_id=10,
            content="hi", template_id=None, mode="manual",
            log_session_id=42,
        )

        mock_factory.assert_called_with("socks5://u:p@h:80")
        mock_client.post.assert_awaited()
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd backend && pytest tests/test_seeding_sender.py::test_send_uses_proxied_client_when_clone_has_proxy -v
```

Expected: AssertionError — current sender uses `get_client()`, not `get_client_for_proxy`.

- [ ] **Step 3: Update sender to use proxy**

In `backend/app/services/seeding_sender.py`:

a) Replace the import line:
```python
from app.services.http_client import get_client
```
with:
```python
from app.services.http_client import get_client_for_proxy
```

b) Change `_post_with_retry` signature and body. Replace the existing method with:

```python
    async def _post_with_retry(
        self, url: str, headers: dict[str, str], body: dict[str, Any],
        proxy_url: str | None,
    ) -> tuple[int, str | None]:
        last_status = 0
        last_err: str | None = None
        for attempt in range(1, 3):
            try:
                await shopee_limiter.acquire()
                client = get_client_for_proxy(proxy_url)
                resp = await client.post(
                    url, headers=headers, json=body, timeout=REPLY_TIMEOUT_SEC,
                )
                last_status = resp.status_code
                if last_status in (401, 403):
                    return last_status, "auth_expired"
                if last_status == 429 and attempt < 2:
                    await asyncio.sleep(2.0)
                    continue
                if last_status == 200:
                    try:
                        if resp.json().get("err_code") == 0:
                            return 200, None
                    except json.JSONDecodeError:
                        pass
                return last_status, f"upstream_{last_status}"
            except Exception as e:
                last_err = type(e).__name__
                logger.error(
                    "seeding send error (attempt %d): %s",
                    attempt, type(e).__name__,
                )
                if attempt < 2:
                    await asyncio.sleep(0.5)
                    continue
                return 0, last_err or "request_failed"
        return last_status, last_err or "rate_limited"
```

c) Update the only call site in `send()`. Find:
```python
        status, err = await self._post_with_retry(url, headers, body)
```
Replace with:
```python
        status, err = await self._post_with_retry(
            url, headers, body, proxy_url=clone.proxy,
        )
```

- [ ] **Step 4: Run test, expect pass**

```bash
cd backend && pytest tests/test_seeding_sender.py::test_send_uses_proxied_client_when_clone_has_proxy -v
```

Expected: PASS.

- [ ] **Step 5: Run full sender test file**

```bash
cd backend && pytest tests/test_seeding_sender.py -v
```

Expected: all existing tests still green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/seeding_sender.py backend/tests/test_seeding_sender.py
git commit -m "feat(seeding): route sender through clone.proxy via cached client"
```

---

## Task 11: Enforce `require_proxy` in sender (TDD)

**Files:**
- Modify: `backend/app/services/seeding_sender.py`
- Modify: `backend/tests/test_seeding_sender.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_seeding_sender.py`:

```python
@pytest.mark.asyncio
async def test_require_proxy_skips_clone_without_proxy_auto_mode():
    sender = SeedingSender()
    fake_clone = type("C", (), {
        "id": 1, "user_id": 7, "name": "C", "cookies": "x",
        "proxy": None, "proxy_id": None,
        "last_sent_at": None, "consecutive_failures": 0,
    })()

    with patch.object(
        sender, "_load_clone", new=AsyncMock(return_value=fake_clone),
    ), patch.object(
        sender, "_get_require_proxy", new=AsyncMock(return_value=True),
    ), patch.object(
        sender, "_record_failure", new=AsyncMock(),
    ), patch.object(
        sender, "_write_log", new=AsyncMock(return_value="log"),
    ) as mock_log, patch(
        "app.services.seeding_sender.get_client_for_proxy",
    ) as mock_factory:
        await sender.send(
            clone_id=1, nick_live_id=1, shopee_session_id=10,
            content="hi", template_id=None, mode="auto",
            log_session_id=42,
        )
        mock_factory.assert_not_called()
        mock_log.assert_awaited()
        kwargs = mock_log.call_args.kwargs
        assert kwargs["status"] == "failed"
        assert kwargs["error"] == "no_proxy"


@pytest.mark.asyncio
async def test_require_proxy_raises_for_manual_mode():
    sender = SeedingSender()
    fake_clone = type("C", (), {
        "id": 1, "user_id": 7, "name": "C", "cookies": "x",
        "proxy": None, "proxy_id": None,
        "last_sent_at": None, "consecutive_failures": 0,
    })()

    with patch.object(
        sender, "_load_clone", new=AsyncMock(return_value=fake_clone),
    ), patch.object(
        sender, "_get_require_proxy", new=AsyncMock(return_value=True),
    ), patch.object(
        sender, "_record_failure", new=AsyncMock(),
    ), patch.object(
        sender, "_write_log", new=AsyncMock(return_value="log"),
    ):
        with pytest.raises(RuntimeError, match="no_proxy"):
            await sender.send(
                clone_id=1, nick_live_id=1, shopee_session_id=10,
                content="hi", template_id=None, mode="manual",
                log_session_id=42,
            )


@pytest.mark.asyncio
async def test_require_proxy_off_allows_direct_send():
    """When require_proxy=False, missing clone.proxy still sends direct."""
    sender = SeedingSender()
    fake_clone = type("C", (), {
        "id": 1, "user_id": 7, "name": "C", "cookies": "x",
        "proxy": None, "proxy_id": None,
        "last_sent_at": None, "consecutive_failures": 0,
    })()
    fake_resp = type("R", (), {
        "status_code": 200, "json": lambda self: {"err_code": 0},
    })()

    with patch.object(
        sender, "_load_clone", new=AsyncMock(return_value=fake_clone),
    ), patch.object(
        sender, "_get_require_proxy", new=AsyncMock(return_value=False),
    ), patch.object(
        sender, "_resolve_host_credentials",
        new=AsyncMock(return_value={"uuid": "u", "usersig": "s"}),
    ), patch.object(
        sender, "_touch_clone_last_sent", new=AsyncMock(),
    ), patch.object(
        sender, "_write_log", new=AsyncMock(return_value="log"),
    ), patch(
        "app.services.seeding_sender.get_client_for_proxy",
    ) as mock_factory, patch(
        "app.services.seeding_sender.shopee_limiter.acquire",
        new=AsyncMock(),
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=fake_resp)
        mock_factory.return_value = mock_client

        await sender.send(
            clone_id=1, nick_live_id=1, shopee_session_id=10,
            content="hi", template_id=None, mode="manual",
            log_session_id=42,
        )
        mock_factory.assert_called_with(None)
```

- [ ] **Step 2: Run tests, expect failure**

```bash
cd backend && pytest tests/test_seeding_sender.py -k require_proxy -v
```

Expected: AttributeError on `_get_require_proxy`.

- [ ] **Step 3: Implement enforcement**

In `backend/app/services/seeding_sender.py`:

a) Add a setting key constant near the top of the file (after imports):

```python
REQUIRE_PROXY_SETTING_KEY = "seeding.require_proxy"
```

b) Add a helper method on `SeedingSender` (after `_load_clone` or near the other async helpers):

```python
    async def _get_require_proxy(self, user_id: int) -> bool:
        return await asyncio.to_thread(
            self._get_require_proxy_sync, user_id,
        )

    def _get_require_proxy_sync(self, user_id: int) -> bool:
        from app.services.settings_service import SettingsService
        with SessionLocal() as db:
            svc = SettingsService(db, user_id=user_id)
            value = svc.get_setting(REQUIRE_PROXY_SETTING_KEY)
            return value == "true"
```

c) In `send()`, after `clone = await self._load_clone(clone_id)` and the rate-limit branch, before resolving host credentials, insert:

```python
        require_proxy = await self._get_require_proxy(clone.user_id)
        if require_proxy and not clone.proxy:
            logger.warning(
                "seeding skipped clone_id=%s name=%s reason=no_proxy",
                clone_id, clone_name,
            )
            await self._record_failure(clone_id, "no_proxy")
            log_row = await self._write_log(
                log_session_id=log_session_id, clone_id=clone_id,
                template_id=template_id, content=content,
                status="failed", error="no_proxy",
            )
            if mode == "manual":
                raise RuntimeError("no_proxy")
            return log_row
```

- [ ] **Step 4: Run tests, expect pass**

```bash
cd backend && pytest tests/test_seeding_sender.py -k require_proxy -v
```

Expected: 3 passed.

- [ ] **Step 5: Run full sender test file**

```bash
cd backend && pytest tests/test_seeding_sender.py -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/seeding_sender.py backend/tests/test_seeding_sender.py
git commit -m "feat(seeding): enforce require_proxy setting in sender"
```

---

## Task 12: Router — CRUD endpoints

**Files:**
- Create: `backend/app/routers/seeding_proxy.py`
- Test: `backend/tests/test_seeding_proxy_router.py`

- [ ] **Step 1: Write failing tests for CRUD**

Create `backend/tests/test_seeding_proxy_router.py`:

```python
"""Integration tests for /api/seeding/proxies router."""
import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine, init_db
from app.dependencies import get_current_user
from app.main import app
from app.models.seeding import SeedingClone, SeedingProxy
from app.models.user import User


def _override_user(u: User):
    app.dependency_overrides[get_current_user] = lambda: u


@pytest.fixture
def user():
    init_db()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(SeedingProxy).delete()
        db.query(User).filter(User.username == "proxyrouter").delete()
        u = User(username="proxyrouter", password_hash="x", role="user")
        db.add(u)
        db.commit()
        db.refresh(u)
        uid = u.id
    with SessionLocal() as db:
        u = db.get(User, uid)
        db.expunge(u)
    _override_user(u)
    yield u
    app.dependency_overrides.clear()
    with SessionLocal() as db:
        db.query(SeedingClone).filter(SeedingClone.user_id == uid).delete()
        db.query(SeedingProxy).filter(SeedingProxy.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def test_create_proxy(user):
    c = TestClient(app)
    r = c.post("/api/seeding/proxies", json={
        "scheme": "socks5", "host": "h.com", "port": 80,
        "username": "u", "password": "p",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["scheme"] == "socks5"
    assert data["host"] == "h.com"
    assert "password" not in data


def test_list_proxies(user):
    c = TestClient(app)
    c.post("/api/seeding/proxies", json={
        "scheme": "http", "host": "h1", "port": 80,
    })
    c.post("/api/seeding/proxies", json={
        "scheme": "http", "host": "h2", "port": 80,
    })
    r = c.get("/api/seeding/proxies")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_update_proxy_refreshes_clone_cache(user):
    c = TestClient(app)
    pr = c.post("/api/seeding/proxies", json={
        "scheme": "http", "host": "old", "port": 80,
        "username": "u", "password": "p",
    }).json()

    # Create a clone and assign
    c.post("/api/seeding/clones", json={
        "name": "C1", "shopee_user_id": 1, "cookies": "x",
    })
    c.post("/api/seeding/proxies/assign", json={"only_unassigned": False})

    # Edit proxy host
    r = c.patch(f"/api/seeding/proxies/{pr['id']}", json={"host": "new"})
    assert r.status_code == 200
    assert r.json()["host"] == "new"

    # Clone cache string must reflect new host
    clones = c.get("/api/seeding/clones").json()
    assert clones[0]["proxy"] == "http://u:p@new:80"


def test_delete_proxy_clears_clone_cache(user):
    c = TestClient(app)
    pr = c.post("/api/seeding/proxies", json={
        "scheme": "http", "host": "h", "port": 80,
    }).json()
    c.post("/api/seeding/clones", json={
        "name": "C1", "shopee_user_id": 1, "cookies": "x",
    })
    c.post("/api/seeding/proxies/assign", json={"only_unassigned": False})

    r = c.delete(f"/api/seeding/proxies/{pr['id']}")
    assert r.status_code == 204

    clones = c.get("/api/seeding/clones").json()
    assert clones[0]["proxy"] is None
    assert clones[0].get("proxy_meta") is None


def test_user_isolation(user):
    c = TestClient(app)
    c.post("/api/seeding/proxies", json={
        "scheme": "http", "host": "h", "port": 80,
    })
    # Create another user, switch override
    with SessionLocal() as db:
        other = User(username="otherproxy", password_hash="x", role="user")
        db.add(other)
        db.commit()
        db.refresh(other)
        other_id = other.id
    try:
        with SessionLocal() as db:
            other = db.get(User, other_id)
            db.expunge(other)
        _override_user(other)
        r = c.get("/api/seeding/proxies")
        assert r.json() == []
    finally:
        with SessionLocal() as db:
            db.query(SeedingProxy).filter(
                SeedingProxy.user_id == other_id
            ).delete()
            db.query(User).filter(User.id == other_id).delete()
            db.commit()
```

- [ ] **Step 2: Run tests, expect failure**

```bash
cd backend && pytest tests/test_seeding_proxy_router.py -v
```

Expected: 404 / route not found.

- [ ] **Step 3: Implement router (CRUD only — assign/import/setting in next task)**

Create `backend/app/routers/seeding_proxy.py`:

```python
"""/api/seeding/proxies — proxy CRUD, bulk import, round-robin assignment."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.seeding import SeedingClone, SeedingProxy
from app.models.user import User
from app.schemas.seeding_proxy import (
    ProxyAssignRequest,
    ProxyAssignResult,
    ProxyCreate,
    ProxyImportRequest,
    ProxyImportResult,
    ProxyOut,
    ProxyUpdate,
    RequireProxySetting,
)
from app.services.seeding_proxy_service import (
    REQUIRE_PROXY_SETTING_KEY,
    assign_round_robin,
    clear_clone_cache_for_proxy,
    format_url,
    import_bulk,
    refresh_clone_cache_for_proxy,
)
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/seeding/proxies", tags=["seeding-proxy"])


def _owned_proxy(db: Session, proxy_id: int, user_id: int) -> SeedingProxy:
    row = db.query(SeedingProxy).filter(
        SeedingProxy.id == proxy_id, SeedingProxy.user_id == user_id
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Proxy not found")
    return row


def _to_out(db: Session, p: SeedingProxy) -> ProxyOut:
    used_by = db.query(SeedingClone).filter(
        SeedingClone.proxy_id == p.id
    ).count()
    return ProxyOut(
        id=p.id, scheme=p.scheme, host=p.host, port=p.port,
        username=p.username, note=p.note, created_at=p.created_at,
        used_by_count=used_by,
    )


@router.get("", response_model=list[ProxyOut])
def list_proxies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProxyOut]:
    rows = (
        db.query(SeedingProxy)
        .filter(SeedingProxy.user_id == current_user.id)
        .order_by(SeedingProxy.id.asc())
        .all()
    )
    return [_to_out(db, p) for p in rows]


@router.post("", response_model=ProxyOut)
def create_proxy(
    payload: ProxyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProxyOut:
    row = SeedingProxy(
        user_id=current_user.id,
        scheme=payload.scheme, host=payload.host, port=payload.port,
        username=payload.username, password=payload.password,
        note=payload.note,
    )
    db.add(row)
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001 — UNIQUE violation
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Proxy already exists",
        ) from exc
    db.refresh(row)
    return _to_out(db, row)


@router.patch("/{proxy_id}", response_model=ProxyOut)
def update_proxy(
    proxy_id: int,
    payload: ProxyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProxyOut:
    row = _owned_proxy(db, proxy_id, current_user.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    refresh_clone_cache_for_proxy(row.id)
    return _to_out(db, row)


@router.delete("/{proxy_id}", status_code=204)
def delete_proxy(
    proxy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    row = _owned_proxy(db, proxy_id, current_user.id)
    clear_clone_cache_for_proxy(row.id)
    db.delete(row)
    db.commit()
    return Response(status_code=204)
```

- [ ] **Step 4: Mount router in `main.py`**

In `backend/app/main.py`, locate the existing `app.include_router(seeding.router)` line and add immediately below it:

```python
from app.routers import seeding_proxy
app.include_router(seeding_proxy.router)
```

(Adjust import location to match the file's existing import style.)

- [ ] **Step 5: Run CRUD tests, expect pass (assign/setting tests will still fail — that's task 13)**

```bash
cd backend && pytest tests/test_seeding_proxy_router.py -k "create or list or update or delete or isolation" -v
```

Expected: 5 passed (assign-dependent tests still fail until next task).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/seeding_proxy.py backend/app/main.py backend/tests/test_seeding_proxy_router.py
git commit -m "feat(seeding): proxy CRUD router endpoints"
```

---

## Task 13: Router — import, assign, setting endpoints

**Files:**
- Modify: `backend/app/routers/seeding_proxy.py`
- Modify: `backend/tests/test_seeding_proxy_router.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_seeding_proxy_router.py`:

```python
def test_import_endpoint(user):
    c = TestClient(app)
    r = c.post("/api/seeding/proxies/import", json={
        "scheme": "socks5",
        "raw_text": "h1:80:u:p\nh2:81:u:p\nbad-line\n",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["created"] == 2
    assert data["skipped_duplicates"] == 0
    assert len(data["errors"]) == 1
    assert data["errors"][0]["reason"] == "invalid_format"


def test_assign_endpoint(user):
    c = TestClient(app)
    c.post("/api/seeding/proxies/import", json={
        "scheme": "http", "raw_text": "h1:80:u:p\nh2:81:u:p\n",
    })
    c.post("/api/seeding/clones", json={
        "name": "C1", "shopee_user_id": 1, "cookies": "x",
    })
    c.post("/api/seeding/clones", json={
        "name": "C2", "shopee_user_id": 2, "cookies": "x",
    })
    c.post("/api/seeding/clones", json={
        "name": "C3", "shopee_user_id": 3, "cookies": "x",
    })

    r = c.post("/api/seeding/proxies/assign", json={"only_unassigned": False})
    assert r.status_code == 200
    assert r.json() == {"assigned": 3, "reason": "ok"}


def test_setting_round_trip(user):
    c = TestClient(app)
    r = c.get("/api/seeding/proxies/setting")
    assert r.status_code == 200
    assert r.json() == {"require_proxy": False}

    r = c.put("/api/seeding/proxies/setting", json={"require_proxy": True})
    assert r.status_code == 200
    assert r.json() == {"require_proxy": True}

    r = c.get("/api/seeding/proxies/setting")
    assert r.json() == {"require_proxy": True}
```

- [ ] **Step 2: Run tests, expect failure**

```bash
cd backend && pytest tests/test_seeding_proxy_router.py -k "import or assign or setting" -v
```

Expected: 404.

- [ ] **Step 3: Add endpoints to `seeding_proxy.py`**

Append to `backend/app/routers/seeding_proxy.py`:

```python
@router.post("/import", response_model=ProxyImportResult)
def import_proxies(
    payload: ProxyImportRequest,
    current_user: User = Depends(get_current_user),
) -> ProxyImportResult:
    return import_bulk(current_user.id, payload.scheme, payload.raw_text)


@router.post("/assign", response_model=ProxyAssignResult)
def assign_proxies(
    payload: ProxyAssignRequest,
    current_user: User = Depends(get_current_user),
) -> ProxyAssignResult:
    return assign_round_robin(current_user.id, payload.only_unassigned)


@router.get("/setting", response_model=RequireProxySetting)
def get_proxy_setting(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RequireProxySetting:
    svc = SettingsService(db, user_id=current_user.id)
    raw = svc.get_setting(REQUIRE_PROXY_SETTING_KEY)
    return RequireProxySetting(require_proxy=(raw == "true"))


@router.put("/setting", response_model=RequireProxySetting)
def set_proxy_setting(
    payload: RequireProxySetting,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RequireProxySetting:
    svc = SettingsService(db, user_id=current_user.id)
    svc.set_setting(
        REQUIRE_PROXY_SETTING_KEY,
        "true" if payload.require_proxy else "false",
    )
    return payload
```

- [ ] **Step 4: Export `REQUIRE_PROXY_SETTING_KEY` from service**

`REQUIRE_PROXY_SETTING_KEY` is currently defined in `seeding_sender.py` (Task 11). Move it to `seeding_proxy_service.py` so both modules can import it without a cycle. In `backend/app/services/seeding_proxy_service.py`, near the top of the file (after imports), add:

```python
REQUIRE_PROXY_SETTING_KEY = "seeding.require_proxy"
```

In `backend/app/services/seeding_sender.py`, replace the local constant definition with:

```python
from app.services.seeding_proxy_service import REQUIRE_PROXY_SETTING_KEY
```

- [ ] **Step 5: Run all router tests**

```bash
cd backend && pytest tests/test_seeding_proxy_router.py -v
```

Expected: all 8 tests passed.

- [ ] **Step 6: Run full backend test suite**

```bash
cd backend && pytest -v
```

Expected: all green; no regressions in existing seeding tests.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/seeding_proxy.py backend/app/services/seeding_proxy_service.py backend/app/services/seeding_sender.py backend/tests/test_seeding_proxy_router.py
git commit -m "feat(seeding): proxy import/assign/setting endpoints"
```

---

## Task 14: Extend `SeedingCloneResponse` with `proxy_meta`

**Files:**
- Modify: `backend/app/schemas/seeding.py`
- Modify: `backend/app/routers/seeding.py`

- [ ] **Step 1: Add `proxy_meta` to schema**

In `backend/app/schemas/seeding.py`, add a new model and extend `SeedingCloneResponse`:

```python
class CloneProxyMeta(BaseModel):
    id: int
    scheme: Literal["socks5", "http", "https"]
    host: str
    port: int
```

In the `SeedingCloneResponse` class, add:

```python
    proxy_meta: CloneProxyMeta | None = None
```

- [ ] **Step 2: Populate `proxy_meta` in list/create/update responses**

In `backend/app/routers/seeding.py`, add a helper near `_owned_clone`:

```python
def _serialize_clone(db: Session, clone: SeedingClone) -> dict:
    base = {
        "id": clone.id,
        "name": clone.name,
        "shopee_user_id": clone.shopee_user_id,
        "avatar": clone.avatar,
        "proxy": clone.proxy,
        "last_sent_at": clone.last_sent_at,
        "consecutive_failures": clone.consecutive_failures,
        "last_status": clone.last_status,
        "last_error": clone.last_error,
        "auto_disabled": clone.auto_disabled,
        "created_at": clone.created_at,
        "proxy_meta": None,
    }
    if clone.proxy_id is not None:
        from app.models.seeding import SeedingProxy
        p = db.get(SeedingProxy, clone.proxy_id)
        if p is not None:
            base["proxy_meta"] = {
                "id": p.id, "scheme": p.scheme,
                "host": p.host, "port": p.port,
            }
    return base
```

Then update each clone-returning endpoint (`create_clone`, `list_clones`, `update_clone`, `revive_clone`) to wrap the row(s) through `_serialize_clone`. For example:

```python
@router.get("/clones", response_model=list[SeedingCloneResponse])
def list_clones(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(SeedingClone)
        .filter(SeedingClone.user_id == current_user.id)
        .order_by(SeedingClone.created_at.desc())
        .all()
    )
    return [_serialize_clone(db, r) for r in rows]
```

Apply the same pattern to the other three endpoints (returning `_serialize_clone(db, row)` instead of `row`).

- [ ] **Step 3: Add a test for `proxy_meta` in clone list**

Append to `backend/tests/test_seeding_router.py`:

```python
def test_list_clones_includes_proxy_meta(user):
    c = TestClient(app)
    c.post("/api/seeding/proxies", json={
        "scheme": "http", "host": "h", "port": 80,
    })
    c.post("/api/seeding/clones", json={
        "name": "C1", "shopee_user_id": 1, "cookies": "x",
    })
    c.post("/api/seeding/proxies/assign", json={"only_unassigned": False})

    clones = c.get("/api/seeding/clones").json()
    assert clones[0]["proxy_meta"] == {
        "id": clones[0]["proxy_meta"]["id"],
        "scheme": "http", "host": "h", "port": 80,
    }
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/test_seeding_router.py -v && pytest tests/test_seeding_proxy_router.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/seeding.py backend/app/routers/seeding.py backend/tests/test_seeding_router.py
git commit -m "feat(seeding): expose proxy_meta on clone responses"
```

---

## Task 15: Frontend API client + hook

**Files:**
- Create: `frontend/src/api/seedingProxy.ts`
- Create: `frontend/src/hooks/useSeedingProxies.ts`
- Modify: `frontend/src/api/seeding.ts`

- [ ] **Step 1: Add `proxy_meta` to `SeedingClone` type**

In `frontend/src/api/seeding.ts`, in the `SeedingClone` interface (around line 5), add:

```typescript
  proxy_meta: {
    id: number;
    scheme: "socks5" | "http" | "https";
    host: string;
    port: number;
  } | null;
```

- [ ] **Step 2: Create proxy API client**

Create `frontend/src/api/seedingProxy.ts`:

```typescript
import apiClient from "./client";

export type ProxyScheme = "socks5" | "http" | "https";

export interface SeedingProxy {
  id: number;
  scheme: ProxyScheme;
  host: string;
  port: number;
  username: string | null;
  note: string | null;
  created_at: string;
  used_by_count: number;
}

export interface ProxyCreatePayload {
  scheme: ProxyScheme;
  host: string;
  port: number;
  username?: string | null;
  password?: string | null;
  note?: string | null;
}

export type ProxyUpdatePatch = Partial<ProxyCreatePayload>;

export interface ProxyImportPayload {
  scheme: ProxyScheme;
  raw_text: string;
}

export interface ProxyImportError {
  line: number;
  raw: string;
  reason: string;
}

export interface ProxyImportResult {
  created: number;
  skipped_duplicates: number;
  errors: ProxyImportError[];
}

export interface ProxyAssignPayload {
  only_unassigned: boolean;
}

export interface ProxyAssignResult {
  assigned: number;
  reason: "ok" | "no_proxies" | "no_clones" | "all_assigned";
}

export interface RequireProxySetting {
  require_proxy: boolean;
}

export async function listProxies(): Promise<SeedingProxy[]> {
  const res = await apiClient.get("/seeding/proxies");
  return res.data;
}

export async function createProxy(
  payload: ProxyCreatePayload,
): Promise<SeedingProxy> {
  const res = await apiClient.post("/seeding/proxies", payload);
  return res.data;
}

export async function updateProxy(
  id: number,
  patch: ProxyUpdatePatch,
): Promise<SeedingProxy> {
  const res = await apiClient.patch(`/seeding/proxies/${id}`, patch);
  return res.data;
}

export async function deleteProxy(id: number): Promise<void> {
  await apiClient.delete(`/seeding/proxies/${id}`);
}

export async function importProxies(
  payload: ProxyImportPayload,
): Promise<ProxyImportResult> {
  const res = await apiClient.post("/seeding/proxies/import", payload);
  return res.data;
}

export async function assignProxies(
  payload: ProxyAssignPayload,
): Promise<ProxyAssignResult> {
  const res = await apiClient.post("/seeding/proxies/assign", payload);
  return res.data;
}

export async function getProxySetting(): Promise<RequireProxySetting> {
  const res = await apiClient.get("/seeding/proxies/setting");
  return res.data;
}

export async function setProxySetting(
  payload: RequireProxySetting,
): Promise<RequireProxySetting> {
  const res = await apiClient.put("/seeding/proxies/setting", payload);
  return res.data;
}
```

- [ ] **Step 3: Create hook**

Create `frontend/src/hooks/useSeedingProxies.ts`:

```typescript
import { useCallback, useEffect, useState } from "react";

import {
  listProxies,
  createProxy,
  updateProxy,
  deleteProxy,
  importProxies,
  assignProxies,
  getProxySetting,
  setProxySetting,
  type ProxyAssignPayload,
  type ProxyAssignResult,
  type ProxyCreatePayload,
  type ProxyImportPayload,
  type ProxyImportResult,
  type ProxyUpdatePatch,
  type SeedingProxy,
} from "../api/seedingProxy";

export interface UseSeedingProxiesResult {
  proxies: SeedingProxy[];
  requireProxy: boolean;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  create: (payload: ProxyCreatePayload) => Promise<void>;
  update: (id: number, patch: ProxyUpdatePatch) => Promise<void>;
  remove: (id: number) => Promise<void>;
  importBulk: (payload: ProxyImportPayload) => Promise<ProxyImportResult>;
  assign: (payload: ProxyAssignPayload) => Promise<ProxyAssignResult>;
  setRequireProxy: (value: boolean) => Promise<void>;
}

export function useSeedingProxies(): UseSeedingProxiesResult {
  const [proxies, setProxies] = useState<SeedingProxy[]>([]);
  const [requireProxy, setRequireProxyState] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, setting] = await Promise.all([
        listProxies(),
        getProxySetting(),
      ]);
      setProxies(list);
      setRequireProxyState(setting.require_proxy);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const create = async (payload: ProxyCreatePayload): Promise<void> => {
    await createProxy(payload);
    await refresh();
  };

  const update = async (
    id: number,
    patch: ProxyUpdatePatch,
  ): Promise<void> => {
    await updateProxy(id, patch);
    await refresh();
  };

  const remove = async (id: number): Promise<void> => {
    await deleteProxy(id);
    await refresh();
  };

  const importBulk = async (
    payload: ProxyImportPayload,
  ): Promise<ProxyImportResult> => {
    const result = await importProxies(payload);
    await refresh();
    return result;
  };

  const assign = async (
    payload: ProxyAssignPayload,
  ): Promise<ProxyAssignResult> => {
    const result = await assignProxies(payload);
    await refresh();
    return result;
  };

  const setRequireProxy = async (value: boolean): Promise<void> => {
    await setProxySetting({ require_proxy: value });
    setRequireProxyState(value);
  };

  return {
    proxies, requireProxy, loading, error,
    refresh, create, update, remove, importBulk, assign, setRequireProxy,
  };
}
```

- [ ] **Step 4: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/seedingProxy.ts frontend/src/hooks/useSeedingProxies.ts frontend/src/api/seeding.ts
git commit -m "feat(seeding): frontend API client and hook for proxies"
```

---

## Task 16: `ProxyImportPanel` component

**Files:**
- Create: `frontend/src/components/seeding/ProxyImportPanel.tsx`

- [ ] **Step 1: Implement component**

Create `frontend/src/components/seeding/ProxyImportPanel.tsx`:

```typescript
import { useState } from "react";
import { Alert, Button, Input, Select, Space, Typography } from "antd";

import type {
  ProxyImportResult,
  ProxyScheme,
} from "../../api/seedingProxy";

const { Text } = Typography;
const { TextArea } = Input;

interface ProxyImportPanelProps {
  onImport: (
    scheme: ProxyScheme,
    rawText: string,
  ) => Promise<ProxyImportResult>;
}

export function ProxyImportPanel({ onImport }: ProxyImportPanelProps) {
  const [scheme, setScheme] = useState<ProxyScheme>("socks5");
  const [rawText, setRawText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ProxyImportResult | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const onSubmit = async () => {
    setBusy(true);
    setErrMsg(null);
    try {
      const r = await onImport(scheme, rawText);
      setResult(r);
      if (r.errors.length === 0) setRawText("");
    } catch (e: unknown) {
      setErrMsg(e instanceof Error ? e.message : "Import thất bại");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Space>
        <Text>Scheme:</Text>
        <Select
          value={scheme}
          onChange={(v) => setScheme(v)}
          style={{ width: 120 }}
          options={[
            { value: "socks5", label: "socks5" },
            { value: "http", label: "http" },
            { value: "https", label: "https" },
          ]}
        />
      </Space>
      <TextArea
        rows={6}
        value={rawText}
        onChange={(e) => setRawText(e.target.value)}
        placeholder="host:port:user:pass (mỗi proxy 1 dòng)"
        style={{ fontFamily: "monospace" }}
      />
      <Button
        type="primary"
        onClick={onSubmit}
        loading={busy}
        disabled={!rawText.trim()}
      >
        Import
      </Button>
      {errMsg && <Alert type="error" message={errMsg} showIcon />}
      {result && (
        <Alert
          type={result.errors.length > 0 ? "warning" : "success"}
          showIcon
          message={
            `Đã thêm ${result.created}, ` +
            `trùng ${result.skipped_duplicates}, ` +
            `lỗi ${result.errors.length}`
          }
          description={
            result.errors.length > 0 ? (
              <ul style={{ marginBottom: 0 }}>
                {result.errors.map((e) => (
                  <li key={e.line}>
                    Dòng {e.line}: <code>{e.raw}</code> ({e.reason})
                  </li>
                ))}
              </ul>
            ) : null
          }
        />
      )}
    </Space>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/seeding/ProxyImportPanel.tsx
git commit -m "feat(seeding): ProxyImportPanel component"
```

---

## Task 17: `ProxyTable` component

**Files:**
- Create: `frontend/src/components/seeding/ProxyTable.tsx`

- [ ] **Step 1: Implement component**

Create `frontend/src/components/seeding/ProxyTable.tsx`:

```typescript
import { useState } from "react";
import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import type {
  ProxyCreatePayload,
  ProxyScheme,
  ProxyUpdatePatch,
  SeedingProxy,
} from "../../api/seedingProxy";

const { Text } = Typography;

interface ProxyTableProps {
  proxies: SeedingProxy[];
  loading: boolean;
  onCreate: (payload: ProxyCreatePayload) => Promise<void>;
  onUpdate: (id: number, patch: ProxyUpdatePatch) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}

const SCHEME_OPTIONS = [
  { value: "socks5", label: "socks5" },
  { value: "http", label: "http" },
  { value: "https", label: "https" },
];

export function ProxyTable({
  proxies, loading, onCreate, onUpdate, onDelete,
}: ProxyTableProps) {
  const [editing, setEditing] = useState<SeedingProxy | null>(null);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm();

  const openCreate = () => {
    form.resetFields();
    form.setFieldsValue({ scheme: "socks5" });
    setCreating(true);
  };

  const openEdit = (p: SeedingProxy) => {
    form.resetFields();
    form.setFieldsValue({
      scheme: p.scheme, host: p.host, port: p.port,
      username: p.username ?? "", password: "", note: p.note ?? "",
    });
    setEditing(p);
  };

  const onSubmit = async () => {
    try {
      const values = await form.validateFields();
      const payload: ProxyCreatePayload = {
        scheme: values.scheme as ProxyScheme,
        host: values.host.trim(),
        port: Number(values.port),
        username: values.username?.trim() || null,
        password: values.password?.trim() || null,
        note: values.note?.trim() || null,
      };
      if (editing) {
        const patch: ProxyUpdatePatch = { ...payload };
        if (!values.password?.trim()) delete patch.password;
        await onUpdate(editing.id, patch);
        setEditing(null);
      } else {
        await onCreate(payload);
        setCreating(false);
      }
    } catch (e: unknown) {
      if (e instanceof Error) message.error(e.message);
    }
  };

  const columns: ColumnsType<SeedingProxy> = [
    {
      title: "Scheme",
      dataIndex: "scheme",
      width: 90,
      render: (v: ProxyScheme) => <Tag>{v}</Tag>,
    },
    {
      title: "Endpoint",
      key: "endpoint",
      render: (_: unknown, p) => `${p.host}:${p.port}`,
    },
    {
      title: "User",
      dataIndex: "username",
      render: (v: string | null) => v ?? <Text type="secondary">—</Text>,
    },
    {
      title: "Note",
      dataIndex: "note",
      render: (v: string | null) => v ?? <Text type="secondary">—</Text>,
    },
    {
      title: "Đang dùng",
      dataIndex: "used_by_count",
      width: 100,
      render: (n: number) => <Tag color={n > 0 ? "blue" : "default"}>{n} clone</Tag>,
    },
    {
      title: "",
      key: "actions",
      width: 100,
      render: (_: unknown, p) => (
        <Space>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEdit(p)}
          />
          <Popconfirm
            title={
              p.used_by_count > 0
                ? `${p.used_by_count} clone đang dùng proxy này. Xoá?`
                : "Xoá proxy này?"
            }
            okText="Xoá"
            cancelText="Huỷ"
            onConfirm={() => onDelete(p.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Space style={{ justifyContent: "space-between", width: "100%" }}>
        <Text strong>Danh sách proxy ({proxies.length})</Text>
        <Button icon={<PlusOutlined />} onClick={openCreate}>
          Thêm thủ công
        </Button>
      </Space>
      <Table<SeedingProxy>
        rowKey="id"
        columns={columns}
        dataSource={proxies}
        loading={loading}
        size="small"
        pagination={false}
      />
      <Modal
        open={creating || editing !== null}
        title={editing ? "Sửa proxy" : "Thêm proxy"}
        onOk={onSubmit}
        onCancel={() => { setCreating(false); setEditing(null); }}
        okText="Lưu"
        cancelText="Huỷ"
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="scheme" label="Scheme"
            rules={[{ required: true }]}
          >
            <Select options={SCHEME_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="host" label="Host"
            rules={[{ required: true, message: "Host bắt buộc" }]}
          >
            <Input placeholder="proxyx3.ddns.net" />
          </Form.Item>
          <Form.Item
            name="port" label="Port"
            rules={[
              { required: true, message: "Port bắt buộc" },
              { type: "number", min: 1, max: 65535, message: "Port không hợp lệ" },
            ]}
          >
            <InputNumber min={1} max={65535} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="username" label="Username">
            <Input />
          </Form.Item>
          <Form.Item
            name="password"
            label={editing ? "Password (để trống = giữ nguyên)" : "Password"}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item name="note" label="Ghi chú">
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/seeding/ProxyTable.tsx
git commit -m "feat(seeding): ProxyTable component with inline create/edit/delete"
```

---

## Task 18: `ProxySettingsModal`

**Files:**
- Create: `frontend/src/components/seeding/ProxySettingsModal.tsx`

- [ ] **Step 1: Implement modal**

Create `frontend/src/components/seeding/ProxySettingsModal.tsx`:

```typescript
import { useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Divider,
  Modal,
  Space,
  Switch,
  Tooltip,
  Typography,
  message,
} from "antd";

import { useSeedingProxies } from "../../hooks/useSeedingProxies";
import { ProxyImportPanel } from "./ProxyImportPanel";
import { ProxyTable } from "./ProxyTable";

const { Title, Text } = Typography;

interface ProxySettingsModalProps {
  open: boolean;
  onClose: () => void;
  cloneCount: number;
  onAfterAssign?: () => void;
}

export function ProxySettingsModal({
  open, onClose, cloneCount, onAfterAssign,
}: ProxySettingsModalProps) {
  const {
    proxies, requireProxy, loading,
    create, update, remove,
    importBulk, assign, setRequireProxy,
  } = useSeedingProxies();

  const [onlyUnassigned, setOnlyUnassigned] = useState(true);
  const [assigning, setAssigning] = useState(false);

  const onAssign = async () => {
    setAssigning(true);
    try {
      const r = await assign({ only_unassigned: onlyUnassigned });
      if (r.reason === "ok") {
        message.success(`Đã gán proxy cho ${r.assigned} clone`);
        onAfterAssign?.();
      } else if (r.reason === "no_proxies") {
        message.warning("Chưa có proxy nào");
      } else if (r.reason === "no_clones") {
        message.warning("Chưa có clone nào");
      } else if (r.reason === "all_assigned") {
        message.info("Tất cả clone đã có proxy");
      }
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : "Gán thất bại");
    } finally {
      setAssigning(false);
    }
  };

  const assignDisabled = proxies.length === 0 || cloneCount === 0;
  const tooltip = proxies.length === 0
    ? "Chưa có proxy"
    : cloneCount === 0 ? "Chưa có clone" : "";

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      title="Setting Proxy (Seeding)"
      width={780}
      destroyOnClose
    >
      <Space direction="vertical" size="large" style={{ width: "100%" }}>
        <Space>
          <Switch
            checked={requireProxy}
            onChange={(v) => setRequireProxy(v).catch((e: unknown) =>
              message.error(e instanceof Error ? e.message : "Lưu thất bại"),
            )}
          />
          <Text>Bắt buộc dùng proxy (skip clone không có proxy)</Text>
        </Space>

        <Divider style={{ margin: 0 }} />
        <Title level={5} style={{ margin: 0 }}>Import hàng loạt</Title>
        <ProxyImportPanel
          onImport={(scheme, raw_text) =>
            importBulk({ scheme, raw_text })
          }
        />

        <Divider style={{ margin: 0 }} />
        <ProxyTable
          proxies={proxies}
          loading={loading}
          onCreate={create}
          onUpdate={update}
          onDelete={remove}
        />

        <Divider style={{ margin: 0 }} />
        <Title level={5} style={{ margin: 0 }}>Gán proxy cho clones</Title>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Checkbox
            checked={onlyUnassigned}
            onChange={(e) => setOnlyUnassigned(e.target.checked)}
          >
            Chỉ gán cho clone chưa có proxy
          </Checkbox>
          <Tooltip title={tooltip}>
            <Button
              type="primary"
              onClick={onAssign}
              loading={assigning}
              disabled={assignDisabled}
            >
              Gán xoay vòng
            </Button>
          </Tooltip>
          {proxies.length > 0 && cloneCount > 0 && (
            <Alert
              type="info"
              showIcon
              message={
                `Hiện có ${proxies.length} proxy và ${cloneCount} clone. ` +
                `Sẽ phân bổ theo round-robin (proxy[i mod ${proxies.length}]).`
              }
            />
          )}
        </Space>
      </Space>
    </Modal>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/seeding/ProxySettingsModal.tsx
git commit -m "feat(seeding): ProxySettingsModal wraps import/table/assign"
```

---

## Task 19: Wire button into `ClonesTab` + render `proxy_meta`

**Files:**
- Modify: `frontend/src/components/seeding/ClonesTab.tsx`

- [ ] **Step 1: Add modal state and button + replace Proxy column rendering**

Replace `frontend/src/components/seeding/ClonesTab.tsx` with:

```typescript
import { useState } from "react";
import {
  Button,
  Input,
  Space,
  Table,
  Tag,
  Typography,
  Popconfirm,
  message,
  Alert,
} from "antd";
import {
  DeleteOutlined,
  PlusOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { useSeedingClones } from "../../hooks/useSeedingClones";
import type { SeedingClone } from "../../api/seeding";
import { ProxySettingsModal } from "./ProxySettingsModal";

const { Title, Text } = Typography;
const { TextArea } = Input;

function getErrorDetail(e: unknown): string {
  if (e instanceof Error) return e.message;
  return "Lỗi không xác định";
}

export function ClonesTab() {
  const { clones, loading, error, refresh, create, remove } =
    useSeedingClones();

  const [jsonText, setJsonText] = useState("");
  const [adding, setAdding] = useState(false);
  const [proxyModalOpen, setProxyModalOpen] = useState(false);

  const onAdd = async () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(jsonText);
    } catch {
      message.error("JSON không hợp lệ");
      return;
    }
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      Array.isArray(parsed)
    ) {
      message.error("JSON phải là một object");
      return;
    }
    setAdding(true);
    try {
      await create(parsed as Parameters<typeof create>[0]);
      message.success("Thêm clone thành công");
      setJsonText("");
    } catch (e: unknown) {
      message.error("Tạo clone thất bại: " + getErrorDetail(e));
    } finally {
      setAdding(false);
    }
  };

  const columns: ColumnsType<SeedingClone> = [
    { title: "Tên", dataIndex: "name", key: "name" },
    { title: "Shopee ID", dataIndex: "shopee_user_id", key: "shopee_user_id" },
    {
      title: "Proxy",
      key: "proxy",
      render: (_: unknown, record) =>
        record.proxy_meta ? (
          <Space size={4}>
            <Tag>{record.proxy_meta.scheme}</Tag>
            <Text>
              {record.proxy_meta.host}:{record.proxy_meta.port}
            </Text>
          </Space>
        ) : (
          <Text type="secondary">— chưa gán —</Text>
        ),
    },
    {
      title: "Last sent",
      dataIndex: "last_sent_at",
      key: "last_sent_at",
      render: (v: string | null) => <Text type="secondary">{v ?? "-"}</Text>,
    },
    {
      title: "",
      key: "actions",
      width: 80,
      render: (_: unknown, record) => (
        <Popconfirm
          title="Xoá clone này?"
          onConfirm={() =>
            remove(record.id).catch((e: unknown) =>
              message.error("Xoá thất bại: " + getErrorDetail(e)),
            )
          }
          okText="Xoá"
          cancelText="Huỷ"
        >
          <Button danger icon={<DeleteOutlined />} size="small" />
        </Popconfirm>
      ),
    },
  ];

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="large">
      <Space style={{ justifyContent: "space-between", width: "100%" }}>
        <Title level={4} style={{ marginBottom: 0 }}>Clone pool</Title>
        <Button
          icon={<SettingOutlined />}
          onClick={() => setProxyModalOpen(true)}
        >
          Setting Proxy
        </Button>
      </Space>

      {error && <Alert type="error" message={error} showIcon closable />}

      <Table<SeedingClone>
        dataSource={clones}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={false}
        size="small"
      />

      <div>
        <Title level={5}>Thêm clone (JSON giống NickLive)</Title>
        <Space direction="vertical" style={{ width: "100%" }}>
          <TextArea
            rows={6}
            value={jsonText}
            placeholder={
              '{\n  "name": "Clone 1",\n  "shopee_user_id": "12345",\n  "cookies": "SPC_EC=..."\n}'
            }
            onChange={(e) => setJsonText(e.target.value)}
            style={{ fontFamily: "monospace" }}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={onAdd}
            loading={adding}
            disabled={!jsonText.trim()}
          >
            Thêm Clone
          </Button>
        </Space>
      </div>

      <ProxySettingsModal
        open={proxyModalOpen}
        onClose={() => setProxyModalOpen(false)}
        cloneCount={clones.length}
        onAfterAssign={refresh}
      />
    </Space>
  );
}
```

- [ ] **Step 2: Type-check + smoke test in dev**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

Then start dev server, open the Seeding page, click "Setting Proxy" — modal opens. Import a single proxy `1.1.1.1:80:u:p` (scheme http), confirm it shows in the table. Add a clone, click "Gán xoay vòng" with `only_unassigned=false`, confirm clone Proxy column shows `http 1.1.1.1:80`.

```bash
cd frontend && npm run dev
```

(Manual step — not automated.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/seeding/ClonesTab.tsx
git commit -m "feat(seeding): wire Setting Proxy modal into Clones tab"
```

---

## Task 20: Final integration verification

**Files:** none (verification only)

- [ ] **Step 1: Run full backend test suite**

```bash
cd backend && pytest -v
```

Expected: all green. No regressions.

- [ ] **Step 2: Run full frontend type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Manual end-to-end smoke**

With backend + frontend running locally, log in as a normal user:

1. Seeding ▸ Clones tab → click "Setting Proxy" → modal opens.
2. Switch "Bắt buộc dùng proxy" off. Import 2 proxies via paste (scheme socks5).
3. Verify both rows visible in proxy table with `0 clone` badge.
4. Close modal. Add 3 clones (any cookies).
5. Open modal again, untick "Chỉ gán cho clone chưa có proxy", click "Gán xoay vòng".
6. Verify toast `Đã gán proxy cho 3 clone`. Close modal. Clones table now shows scheme + host:port for each clone (proxy 1, proxy 2, proxy 1).
7. Edit proxy 1 host in modal — verify both clones using it now display the new host.
8. Delete proxy 1 — verify the two clones using it now show `— chưa gán —`.
9. Toggle "Bắt buộc dùng proxy" on. Manually send to a clone whose proxy is NULL — backend should respond with error `no_proxy`; UI surfaces the error.

- [ ] **Step 4: Final commit (if any housekeeping changes)**

If verification surfaces nothing, no commit. Otherwise commit fixes per existing pattern.

---

## Self-Review Notes

**Spec coverage check:**
- Decision 1 (format): Tasks 4, 16. ✅
- Decision 2 (scheme dropdown): Tasks 16, 17. ✅
- Decision 3 (assign button + only-unassigned): Tasks 7, 13, 18. ✅
- Decision 4 (table + FK + cache): Tasks 1, 2, 8, 12. ✅
- Decision 5 (require_proxy toggle): Tasks 11, 13, 18. ✅
- Decision 6 (button in Clones toolbar): Task 19. ✅
- Sender wiring: Tasks 9, 10. ✅
- All edge cases listed in spec are covered by service tests in Tasks 7, 8 and router tests in Tasks 12, 13. ✅
- Open question (no reveal-password endpoint): honored — `ProxyOut` excludes password (Task 3); edit form treats blank password as "keep" (Task 17). ✅

**Type consistency check:**
- `ParsedProxy`, `ParseError`, `ProxyImportError`, `ProxyImportResult`, `ProxyAssignResult` defined in Task 3, used identically in Tasks 4, 6, 7, 13.
- `format_url`, `import_bulk`, `assign_round_robin`, `refresh_clone_cache_for_proxy`, `clear_clone_cache_for_proxy`, `REQUIRE_PROXY_SETTING_KEY` all live in `seeding_proxy_service.py` and are imported by the same names in Tasks 12 and 13.
- `proxy_meta` shape (id/scheme/host/port) consistent between backend serializer (Task 14) and frontend types (Task 15) and renderer (Task 19).
- Sender uses `clone.proxy` (cached URL string) — service writes that field in `assign_round_robin` (Task 7) and `refresh_clone_cache_for_proxy` (Task 8). Sender path (Task 10) reads it correctly.
