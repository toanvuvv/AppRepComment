# Auto Pin Random Product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-nick auto-pin loop that calls `POST https://api.relive.vn/livestream/show` on a random min/max minute interval to pin random in-stock `KnowledgeProduct` items during a livestream.

**Architecture:** Mirror the existing `AutoPoster` pattern — a singleton `AutoPinner` service holding per-nick asyncio tasks, started/stopped via dedicated endpoints, configured via 3 new columns on `nick_live_settings`. Pure-random pick from `in_stock=True` products each cycle. No persistence of pin history.

**Tech Stack:** FastAPI · SQLAlchemy · SQLite · asyncio · pytest · httpx · React/TypeScript (Vite)

**Spec:** [docs/superpowers/specs/2026-04-20-auto-pin-random-product-design.md](../specs/2026-04-20-auto-pin-random-product-design.md)

---

## File Structure

**New:**
- `backend/app/services/auto_pinner.py` — `AutoPinner` service (per-nick asyncio loops)
- `backend/tests/test_auto_pinner.py` — unit tests
- `backend/tests/test_auto_pin_router.py` — router tests

**Modified:**
- `backend/app/models/settings.py` — 3 cột mới trên `NickLiveSetting`
- `backend/app/database.py` — thêm entries vào `_migrate_add_columns` list
- `backend/app/schemas/settings.py` — thêm pin fields vào `NickLiveSettingsUpdate` + `NickLiveSettingsResponse` + tạo `AutoPinStartRequest`
- `backend/app/services/relive_service.py` — thêm hàm `pin_livestream_item`
- `backend/app/services/settings_service.py` — extend `update_nick_settings` với 3 kwargs mới
- `backend/app/routers/nick_live.py` — 3 endpoints `/auto-pin/start|stop|status` + include pin fields khi update settings
- `backend/app/main.py` — khởi tạo `auto_pinner` singleton trong `lifespan`, gọi `stop_all` khi shutdown
- `backend/app/routers/admin.py` — gọi `auto_pinner.stop_user_nicks` khi lock/delete user
- `backend/tests/test_relive_service.py` hoặc file mới — test cho `pin_livestream_item`
- `frontend/src/components/NickConfigModal.tsx` — section "Auto Pin sản phẩm"
- `frontend/src/api/` (nơi có sẵn các hàm auto-post) — thêm `startAutoPin`, `stopAutoPin`, `getAutoPinStatus`

---

## Task 1: Data Model + Migration

**Files:**
- Modify: `backend/app/models/settings.py`
- Modify: `backend/app/database.py` (function `_migrate_add_columns`)

- [ ] **Step 1: Add 3 columns to `NickLiveSetting`**

Edit `backend/app/models/settings.py` — thêm vào class `NickLiveSetting` (sau block `# --- Auto-post config ---`, trước `# --- Credentials ---`):

```python
    # --- Auto-pin config ---
    auto_pin_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pin_min_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    pin_max_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
```

- [ ] **Step 2: Add migration entries**

Edit `backend/app/database.py`, `_migrate_add_columns` function. Append to the `migrations` list (before the `for table, column, sql in migrations:` loop):

```python
        (
            "nick_live_settings",
            "auto_pin_enabled",
            "ALTER TABLE nick_live_settings ADD COLUMN auto_pin_enabled BOOLEAN NOT NULL DEFAULT 0",
        ),
        (
            "nick_live_settings",
            "pin_min_interval_minutes",
            "ALTER TABLE nick_live_settings ADD COLUMN pin_min_interval_minutes INTEGER NOT NULL DEFAULT 2",
        ),
        (
            "nick_live_settings",
            "pin_max_interval_minutes",
            "ALTER TABLE nick_live_settings ADD COLUMN pin_max_interval_minutes INTEGER NOT NULL DEFAULT 5",
        ),
```

- [ ] **Step 3: Verify migration runs cleanly**

Run from `backend/`:

```bash
python -c "from app.database import init_db; init_db(); print('OK')"
```

Expected: `OK` (no stack trace). Verify columns exist:

```bash
python -c "import sqlite3; c=sqlite3.connect('database.db').cursor(); c.execute('PRAGMA table_info(nick_live_settings)'); [print(r) for r in c.fetchall()]"
```

Expected: output includes rows with `auto_pin_enabled`, `pin_min_interval_minutes`, `pin_max_interval_minutes`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/settings.py backend/app/database.py
git commit -m "feat(db): add auto-pin columns to nick_live_settings"
```

---

## Task 2: Pydantic Schemas

**Files:**
- Modify: `backend/app/schemas/settings.py`

- [ ] **Step 1: Extend `NickLiveSettingsUpdate` + Response**

Edit `backend/app/schemas/settings.py`. Replace `NickLiveSettingsUpdate` and `NickLiveSettingsResponse` with:

```python
from pydantic import BaseModel, Field, model_validator


class NickLiveSettingsUpdate(BaseModel):
    reply_mode: ReplyMode | None = None
    reply_to_host: bool | None = None
    reply_to_moderator: bool | None = None
    auto_post_enabled: bool | None = None
    auto_post_to_host: bool | None = None
    auto_post_to_moderator: bool | None = None
    host_proxy: str | None = None

    # Auto-pin fields
    auto_pin_enabled: bool | None = None
    pin_min_interval_minutes: int | None = Field(default=None, ge=1, le=60)
    pin_max_interval_minutes: int | None = Field(default=None, ge=1, le=60)

    @model_validator(mode="after")
    def _check_pin_interval(self):
        lo, hi = self.pin_min_interval_minutes, self.pin_max_interval_minutes
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("pin_min_interval_minutes phải <= pin_max_interval_minutes")
        return self


class NickLiveSettingsResponse(BaseModel):
    nick_live_id: int
    reply_mode: ReplyMode
    reply_to_host: bool
    reply_to_moderator: bool
    auto_post_enabled: bool
    auto_post_to_host: bool
    auto_post_to_moderator: bool
    auto_pin_enabled: bool
    pin_min_interval_minutes: int
    pin_max_interval_minutes: int
    model_config = {"from_attributes": True}
```

(Ensure `model_validator` is imported. If `Field` already imported, just add `model_validator`.)

- [ ] **Step 2: Add `AutoPinStartRequest` schema**

Append at end of `backend/app/schemas/settings.py`:

```python
class AutoPinStartRequest(BaseModel):
    session_id: int = Field(gt=0)
```

- [ ] **Step 3: Smoke-check import**

```bash
cd backend && python -c "from app.schemas.settings import NickLiveSettingsUpdate, AutoPinStartRequest; NickLiveSettingsUpdate(pin_min_interval_minutes=5, pin_max_interval_minutes=3)"
```

Expected: raises `ValidationError` with message mentioning `pin_min_interval_minutes phải <= pin_max_interval_minutes`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas/settings.py
git commit -m "feat(schema): add auto-pin fields + AutoPinStartRequest"
```

---

## Task 3: `relive_service.pin_livestream_item`

**Files:**
- Modify: `backend/app/services/relive_service.py`
- Create or modify: `backend/tests/test_relive_service.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_relive_service.py` (if not exists). Append:

```python
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.relive_service import pin_livestream_item


@pytest.mark.asyncio
async def test_pin_livestream_item_payload_shape():
    fake_resp = type("R", (), {"status_code": 200, "text": '{"ok":1}',
                               "json": lambda self: {"ok": 1}})()
    mock_client = type("C", (), {})()
    mock_client.post = AsyncMock(return_value=fake_resp)

    with patch("app.services.relive_service.get_client", return_value=mock_client):
        result = await pin_livestream_item(
            api_key="K", cookies="C", session_id=111,
            item_id=222, shop_id=333, proxy=None,
        )

    assert result == {"ok": 1}
    mock_client.post.assert_awaited_once()
    url, = mock_client.post.await_args.args
    kwargs = mock_client.post.await_args.kwargs
    assert url == "https://api.relive.vn/livestream/show"
    payload = kwargs["json"]
    assert payload["apikey"] == "K"
    assert payload["cookie"] == "C"
    assert payload["session_id"] == 111
    assert json.loads(payload["item"]) == {"item_id": 222, "shop_id": 333}
    assert payload["country"] == "vn"
    assert payload["proxy"] == ""


@pytest.mark.asyncio
async def test_pin_livestream_item_http_error():
    fake_resp = type("R", (), {"status_code": 500, "text": "boom"})()
    mock_client = type("C", (), {})()
    mock_client.post = AsyncMock(return_value=fake_resp)

    with patch("app.services.relive_service.get_client", return_value=mock_client):
        with pytest.raises(ValueError, match="status 500"):
            await pin_livestream_item(
                api_key="K", cookies="C", session_id=1,
                item_id=2, shop_id=3,
            )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && pytest tests/test_relive_service.py -v
```

Expected: FAIL with `ImportError: cannot import name 'pin_livestream_item'`.

- [ ] **Step 3: Implement `pin_livestream_item`**

Edit `backend/app/services/relive_service.py`. Add `import json` at top if missing. At end of file add:

```python
_RELIVE_SHOW_URL = "https://api.relive.vn/livestream/show"


async def pin_livestream_item(
    api_key: str,
    cookies: str,
    session_id: int,
    item_id: int,
    shop_id: int,
    proxy: str | None = None,
) -> dict[str, Any]:
    """Call relive.vn /livestream/show to pin an item onto the live stream.

    Returns the parsed JSON response on success.
    Raises ValueError on any failure with a descriptive message.
    """
    payload: dict[str, Any] = {
        "apikey": api_key,
        "cookie": cookies,
        "session_id": session_id,
        "item": json.dumps({"item_id": item_id, "shop_id": shop_id}),
        "country": "vn",
        "proxy": proxy or "",
    }

    client = get_client()
    try:
        resp = await client.post(_RELIVE_SHOW_URL, json=payload, timeout=30.0)
    except Exception as exc:
        raise ValueError(f"Relive.vn pin request failed: {exc}") from exc

    if resp.status_code != 200:
        raise ValueError(
            f"Relive.vn pin returned status {resp.status_code}: {resp.text[:300]}"
        )

    try:
        return resp.json()
    except Exception as exc:
        raise ValueError(f"Relive.vn pin returned invalid JSON: {exc}") from exc
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && pytest tests/test_relive_service.py -v
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/relive_service.py backend/tests/test_relive_service.py
git commit -m "feat(relive): add pin_livestream_item for POST /livestream/show"
```

---

## Task 4: `AutoPinner` Service

**Files:**
- Create: `backend/app/services/auto_pinner.py`
- Create: `backend/tests/test_auto_pinner.py`

- [ ] **Step 1: Write failing tests for start guards**

Create `backend/tests/test_auto_pinner.py`:

```python
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.services.auto_pinner import AutoPinner


@pytest.fixture
def pinner():
    p = AutoPinner()
    yield p
    p.stop_all()


@pytest.mark.asyncio
async def test_start_requires_enabled(pinner):
    settings = MagicMock(auto_pin_enabled=False,
                         pin_min_interval_minutes=2, pin_max_interval_minutes=5)
    with patch.object(pinner, "_load_settings", return_value=(settings, 1)):
        r = await pinner.start(nick_live_id=1, session_id=100, cookies="c")
    assert "error" in r
    assert "chưa được bật" in r["error"].lower()


@pytest.mark.asyncio
async def test_start_requires_api_key(pinner):
    settings = MagicMock(auto_pin_enabled=True,
                         pin_min_interval_minutes=2, pin_max_interval_minutes=5)
    with patch.object(pinner, "_load_settings", return_value=(settings, 1)), \
         patch.object(pinner, "_load_api_key", return_value=None), \
         patch.object(pinner, "_count_in_stock", return_value=3):
        r = await pinner.start(nick_live_id=1, session_id=100, cookies="c")
    assert "error" in r
    assert "relive api key" in r["error"].lower()


@pytest.mark.asyncio
async def test_start_requires_in_stock_products(pinner):
    settings = MagicMock(auto_pin_enabled=True,
                         pin_min_interval_minutes=2, pin_max_interval_minutes=5)
    with patch.object(pinner, "_load_settings", return_value=(settings, 1)), \
         patch.object(pinner, "_load_api_key", return_value="KEY"), \
         patch.object(pinner, "_count_in_stock", return_value=0):
        r = await pinner.start(nick_live_id=1, session_id=100, cookies="c")
    assert "error" in r
    assert "còn hàng" in r["error"].lower()


@pytest.mark.asyncio
async def test_start_idempotent(pinner):
    settings = MagicMock(auto_pin_enabled=True,
                         pin_min_interval_minutes=2, pin_max_interval_minutes=5)
    with patch.object(pinner, "_load_settings", return_value=(settings, 1)), \
         patch.object(pinner, "_load_api_key", return_value="KEY"), \
         patch.object(pinner, "_count_in_stock", return_value=3), \
         patch.object(pinner, "_loop", new=AsyncMock(side_effect=lambda *a, **k: asyncio.sleep(10))):
        r1 = await pinner.start(nick_live_id=1, session_id=100, cookies="c")
        r2 = await pinner.start(nick_live_id=1, session_id=100, cookies="c")
    assert r1 == {"status": "started"}
    assert r2 == {"status": "already_running"}


@pytest.mark.asyncio
async def test_stop_cancels_task(pinner):
    settings = MagicMock(auto_pin_enabled=True,
                         pin_min_interval_minutes=2, pin_max_interval_minutes=5)

    async def long_sleep(*a, **k):
        await asyncio.sleep(60)

    with patch.object(pinner, "_load_settings", return_value=(settings, 1)), \
         patch.object(pinner, "_load_api_key", return_value="KEY"), \
         patch.object(pinner, "_count_in_stock", return_value=3), \
         patch.object(pinner, "_loop", new=AsyncMock(side_effect=long_sleep)):
        await pinner.start(nick_live_id=1, session_id=100, cookies="c")
        assert pinner.is_running(1)
        r = await pinner.stop(1)
    assert r == {"status": "stopped"}
    assert not pinner.is_running(1)


@pytest.mark.asyncio
async def test_stop_user_nicks(pinner):
    settings = MagicMock(auto_pin_enabled=True,
                         pin_min_interval_minutes=2, pin_max_interval_minutes=5)

    async def long_sleep(*a, **k):
        await asyncio.sleep(60)

    with patch.object(pinner, "_load_settings", return_value=(settings, 42)), \
         patch.object(pinner, "_load_api_key", return_value="KEY"), \
         patch.object(pinner, "_count_in_stock", return_value=3), \
         patch.object(pinner, "_loop", new=AsyncMock(side_effect=long_sleep)), \
         patch.object(pinner, "_user_nick_ids", return_value=[1, 2]):
        await pinner.start(nick_live_id=1, session_id=100, cookies="c")
        await pinner.start(nick_live_id=2, session_id=100, cookies="c")
        pinner.stop_user_nicks(42)
        await asyncio.sleep(0.05)
    assert not pinner.is_running(1)
    assert not pinner.is_running(2)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_auto_pinner.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.auto_pinner'`.

- [ ] **Step 3: Implement `AutoPinner`**

Create `backend/app/services/auto_pinner.py`:

```python
"""Auto-pin worker: on a random min/max interval pins a random in-stock product."""

import asyncio
import logging
import random
from typing import Any

from app.database import SessionLocal

logger = logging.getLogger(__name__)


class AutoPinner:
    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}

    def is_running(self, nick_live_id: int) -> bool:
        task = self._tasks.get(nick_live_id)
        return task is not None and not task.done()

    # --- Data loaders (overridable in tests via patch.object) ---

    def _load_settings(self, nick_live_id: int):
        """Return (NickLiveSetting, user_id). Raises if nick not found."""
        from app.models.nick_live import NickLive
        from app.services.settings_service import SettingsService
        with SessionLocal() as db:
            nick = db.query(NickLive).filter(NickLive.id == nick_live_id).first()
            if not nick:
                raise ValueError(f"Nick not found: {nick_live_id}")
            svc = SettingsService(db, user_id=nick.user_id)
            row = svc.get_or_create_nick_settings(nick_live_id)
            # Detach from session to use after close.
            db.expunge(row)
            return row, nick.user_id

    def _load_api_key(self, user_id: int) -> str | None:
        from app.services.settings_service import SettingsService
        with SessionLocal() as db:
            svc = SettingsService(db, user_id=user_id)
            return svc.get_setting("relive_api_key")

    def _count_in_stock(self, nick_live_id: int) -> int:
        from app.models.knowledge_product import KnowledgeProduct
        with SessionLocal() as db:
            return (
                db.query(KnowledgeProduct)
                .filter(
                    KnowledgeProduct.nick_live_id == nick_live_id,
                    KnowledgeProduct.in_stock.is_(True),
                )
                .count()
            )

    def _load_in_stock_products(self, nick_live_id: int) -> list:
        from app.models.knowledge_product import KnowledgeProduct
        with SessionLocal() as db:
            rows = (
                db.query(KnowledgeProduct)
                .filter(
                    KnowledgeProduct.nick_live_id == nick_live_id,
                    KnowledgeProduct.in_stock.is_(True),
                )
                .all()
            )
            # Snapshot just the fields we need so the session can close.
            return [(r.item_id, r.shop_id) for r in rows]

    def _user_nick_ids(self, user_id: int) -> list[int]:
        from app.models.nick_live import NickLive
        with SessionLocal() as db:
            return [nid for (nid,) in db.query(NickLive.id)
                    .filter(NickLive.user_id == user_id).all()]

    # --- Lifecycle ---

    async def start(
        self, nick_live_id: int, session_id: int, cookies: str,
    ) -> dict[str, Any]:
        if self.is_running(nick_live_id):
            return {"status": "already_running"}

        try:
            settings, user_id = self._load_settings(nick_live_id)
        except ValueError as exc:
            return {"error": str(exc)}

        if not settings.auto_pin_enabled:
            return {"error": "Auto Pin chưa được bật"}

        if self._count_in_stock(nick_live_id) == 0:
            return {"error": "Chưa có sản phẩm còn hàng để pin"}

        api_key = self._load_api_key(user_id)
        if not api_key:
            return {"error": "Chưa cấu hình Relive API key"}

        task = asyncio.create_task(self._loop(nick_live_id, session_id, cookies))
        self._tasks[nick_live_id] = task
        logger.info(f"Auto-pin started for nick={nick_live_id}")
        return {"status": "started"}

    async def stop(self, nick_live_id: int) -> dict[str, Any]:
        task = self._tasks.pop(nick_live_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info(f"Auto-pin stopped for nick={nick_live_id}")
            return {"status": "stopped"}
        return {"status": "not_running"}

    def stop_all(self) -> None:
        for nick_id in list(self._tasks):
            task = self._tasks.pop(nick_id)
            if not task.done():
                task.cancel()

    def stop_user_nicks(self, user_id: int) -> None:
        for nid in self._user_nick_ids(user_id):
            task = self._tasks.pop(nid, None)
            if task and not task.done():
                task.cancel()
                logger.info(f"Auto-pin stopped (lock) for nick={nid} user={user_id}")

    def start_user_nicks(self, user_id: int) -> None:
        """No-op — frontend re-triggers start when needed (parity with AutoPoster)."""
        logger.info(f"start_user_nicks(pin) called for user={user_id} (no-op)")

    # --- Loop body ---

    async def _loop(self, nick_live_id: int, session_id: int, cookies: str) -> None:
        from app.services.relive_service import pin_livestream_item
        try:
            while True:
                try:
                    settings, user_id = self._load_settings(nick_live_id)
                except Exception:
                    logger.exception(f"Auto-pin nick={nick_live_id}: settings load failed")
                    await asyncio.sleep(60)
                    continue

                lo = max(1, int(settings.pin_min_interval_minutes)) * 60
                hi = max(lo, int(settings.pin_max_interval_minutes) * 60)
                interval = random.uniform(lo, hi)
                logger.debug(f"Auto-pin nick={nick_live_id}: sleeping {interval:.0f}s")
                await asyncio.sleep(interval)

                products = self._load_in_stock_products(nick_live_id)
                if not products:
                    logger.warning(
                        f"Auto-pin nick={nick_live_id}: no in_stock products, retry next cycle"
                    )
                    continue

                item_id, shop_id = random.choice(products)
                api_key = self._load_api_key(user_id)
                if not api_key:
                    logger.warning(f"Auto-pin nick={nick_live_id}: missing relive_api_key")
                    continue

                proxy = getattr(settings, "host_proxy", None)
                try:
                    await pin_livestream_item(
                        api_key=api_key,
                        cookies=cookies,
                        session_id=session_id,
                        item_id=item_id,
                        shop_id=shop_id,
                        proxy=proxy,
                    )
                    logger.info(
                        f"Auto-pin nick={nick_live_id} item={item_id} shop={shop_id}"
                    )
                except Exception:
                    logger.exception(f"Auto-pin failed nick={nick_live_id}")
                    # swallow — continue loop

        except asyncio.CancelledError:
            logger.info(f"Auto-pin loop cancelled for nick={nick_live_id}")
        except Exception:
            logger.exception(f"Auto-pin loop crashed for nick={nick_live_id}")
        finally:
            self._tasks.pop(nick_live_id, None)
```

- [ ] **Step 4: Run start-guard / stop tests to verify they pass**

```bash
cd backend && pytest tests/test_auto_pinner.py -v
```

Expected: `6 passed`.

- [ ] **Step 5: Add loop-behaviour tests**

Append to `backend/tests/test_auto_pinner.py`:

```python
@pytest.mark.asyncio
async def test_loop_picks_only_in_stock_and_calls_relive(pinner, monkeypatch):
    settings = MagicMock(auto_pin_enabled=True,
                         pin_min_interval_minutes=1, pin_max_interval_minutes=1,
                         host_proxy=None)
    calls = []

    async def fake_pin(**kwargs):
        calls.append(kwargs)
        return {"ok": 1}

    async def fast_sleep(_):
        return None  # interval 0

    monkeypatch.setattr("app.services.auto_pinner.asyncio.sleep", fast_sleep)
    monkeypatch.setattr(
        "app.services.relive_service.pin_livestream_item", fake_pin
    )

    with patch.object(pinner, "_load_settings", return_value=(settings, 7)), \
         patch.object(pinner, "_load_api_key", return_value="KEY"), \
         patch.object(pinner, "_load_in_stock_products",
                      return_value=[(111, 222)]):
        task = asyncio.create_task(pinner._loop(1, 500, "cookies"))
        await asyncio.sleep(0)  # let loop tick
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert any(
        c["item_id"] == 111 and c["shop_id"] == 222 and c["session_id"] == 500
        for c in calls
    )


@pytest.mark.asyncio
async def test_loop_skips_when_no_in_stock(pinner, monkeypatch):
    settings = MagicMock(auto_pin_enabled=True,
                         pin_min_interval_minutes=1, pin_max_interval_minutes=1,
                         host_proxy=None)
    pin_calls = []

    async def fake_pin(**kwargs):
        pin_calls.append(kwargs)

    async def fast_sleep(_):
        return None

    monkeypatch.setattr("app.services.auto_pinner.asyncio.sleep", fast_sleep)
    monkeypatch.setattr(
        "app.services.relive_service.pin_livestream_item", fake_pin
    )

    with patch.object(pinner, "_load_settings", return_value=(settings, 7)), \
         patch.object(pinner, "_load_api_key", return_value="KEY"), \
         patch.object(pinner, "_load_in_stock_products", return_value=[]):
        task = asyncio.create_task(pinner._loop(1, 500, "cookies"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert pin_calls == []


@pytest.mark.asyncio
async def test_loop_swallows_relive_error(pinner, monkeypatch):
    settings = MagicMock(auto_pin_enabled=True,
                         pin_min_interval_minutes=1, pin_max_interval_minutes=1,
                         host_proxy=None)

    async def fail_pin(**kwargs):
        raise ValueError("boom")

    async def fast_sleep(_):
        return None

    monkeypatch.setattr("app.services.auto_pinner.asyncio.sleep", fast_sleep)
    monkeypatch.setattr(
        "app.services.relive_service.pin_livestream_item", fail_pin
    )

    with patch.object(pinner, "_load_settings", return_value=(settings, 7)), \
         patch.object(pinner, "_load_api_key", return_value="KEY"), \
         patch.object(pinner, "_load_in_stock_products",
                      return_value=[(1, 2)]):
        task = asyncio.create_task(pinner._loop(1, 500, "cookies"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # Task should still be alive (not crashed by ValueError)
        assert not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
```

- [ ] **Step 6: Run all AutoPinner tests**

```bash
cd backend && pytest tests/test_auto_pinner.py -v
```

Expected: `9 passed`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/auto_pinner.py backend/tests/test_auto_pinner.py
git commit -m "feat(auto-pin): add AutoPinner service with random in-stock pick loop"
```

---

## Task 5: Extend `SettingsService.update_nick_settings`

**Files:**
- Modify: `backend/app/services/settings_service.py`

- [ ] **Step 1: Add 3 kwargs to `update_nick_settings`**

Edit `backend/app/services/settings_service.py`, function `update_nick_settings`. Change signature — add 3 new kwargs after `host_proxy`:

```python
    def update_nick_settings(
        self,
        nick_live_id: int,
        *,
        reply_mode: str | None = None,
        reply_to_host: bool | None = None,
        reply_to_moderator: bool | None = None,
        auto_post_enabled: bool | None = None,
        auto_post_to_host: bool | None = None,
        auto_post_to_moderator: bool | None = None,
        host_proxy: str | None = None,
        auto_pin_enabled: bool | None = None,
        pin_min_interval_minutes: int | None = None,
        pin_max_interval_minutes: int | None = None,
    ) -> NickLiveSetting:
```

- [ ] **Step 2: Apply the values at the bottom of the method**

Still in `update_nick_settings`, after existing assignments (e.g. after the block that sets `row.host_proxy`), before `self._db.commit()`, append:

```python
        if auto_pin_enabled is not None:
            row.auto_pin_enabled = auto_pin_enabled
        if pin_min_interval_minutes is not None:
            row.pin_min_interval_minutes = pin_min_interval_minutes
        if pin_max_interval_minutes is not None:
            row.pin_max_interval_minutes = pin_max_interval_minutes

        # Cross-field invariant guard (in case only one side provided earlier).
        if row.pin_min_interval_minutes > row.pin_max_interval_minutes:
            raise ValueError("pin_min_interval_minutes phải <= pin_max_interval_minutes")
```

(If you can't find the exact location, the rule: place these lines **before** `self._db.commit()` and `self._db.refresh(row)` at the end of the method.)

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/settings_service.py
git commit -m "feat(settings): persist auto-pin fields via update_nick_settings"
```

---

## Task 6: API Router — settings + start/stop/status

**Files:**
- Modify: `backend/app/routers/nick_live.py`
- Create: `backend/tests/test_auto_pin_router.py`

- [ ] **Step 1: Wire auto-pin fields into PUT settings**

Edit `backend/app/routers/nick_live.py`, function `update_nick_settings` (around line 420–450). Find the `svc.update_nick_settings(...)` call with keyword args `auto_post_enabled=payload.auto_post_enabled` etc. Add 3 lines:

```python
        row = svc.update_nick_settings(
            nick_live_id,
            reply_mode=payload.reply_mode,
            reply_to_host=payload.reply_to_host,
            reply_to_moderator=payload.reply_to_moderator,
            auto_post_enabled=payload.auto_post_enabled,
            auto_post_to_host=payload.auto_post_to_host,
            auto_post_to_moderator=payload.auto_post_to_moderator,
            host_proxy=payload.host_proxy,
            auto_pin_enabled=payload.auto_pin_enabled,
            pin_min_interval_minutes=payload.pin_min_interval_minutes,
            pin_max_interval_minutes=payload.pin_max_interval_minutes,
        )
```

(Keep any surrounding try/except intact.)

- [ ] **Step 2: Add `AutoPinStartRequest` import**

At top of `backend/app/routers/nick_live.py`, in the `from app.schemas.settings import (...)` block, add `AutoPinStartRequest`:

```python
from app.schemas.settings import (
    # ...existing...
    AutoPinStartRequest,
)
```

- [ ] **Step 3: Add 3 auto-pin endpoints**

Append to `backend/app/routers/nick_live.py` (after the `auto_post_status` endpoint around line 553, before `# --- Manual host comment ---`):

```python
# --- Auto-pin control ---


@router.post("/{nick_live_id}/auto-pin/start")
async def auto_pin_start(
    nick_live_id: int,
    payload: AutoPinStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start auto-pin loop for this nick."""
    nick = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == current_user.id
    ).first()
    if not nick:
        raise HTTPException(status_code=404, detail="NickLive not found")

    from app.main import auto_pinner
    if auto_pinner is None:
        raise HTTPException(status_code=503, detail="Auto-pin service not ready")

    result = await auto_pinner.start(nick_live_id, payload.session_id, nick.cookies)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{nick_live_id}/auto-pin/stop")
async def auto_pin_stop(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stop auto-pin loop for this nick."""
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    from app.main import auto_pinner
    if auto_pinner is None:
        return {"status": "not_running"}
    return await auto_pinner.stop(nick_live_id)


@router.get("/{nick_live_id}/auto-pin/status")
def auto_pin_status(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check if auto-pin is running."""
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    from app.main import auto_pinner
    running = auto_pinner.is_running(nick_live_id) if auto_pinner is not None else False
    return {"running": running}
```

- [ ] **Step 4: Write router tests**

Create `backend/tests/test_auto_pin_router.py`:

```python
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_update_settings_rejects_min_gt_max(client, auth_headers, owned_nick):
    """PATCH /settings with min>max → 422 from Pydantic."""
    r = client.put(
        f"/api/nick-lives/{owned_nick}/settings",
        headers=auth_headers,
        json={"pin_min_interval_minutes": 10, "pin_max_interval_minutes": 3},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_update_settings_rejects_out_of_range(client, auth_headers, owned_nick):
    r = client.put(
        f"/api/nick-lives/{owned_nick}/settings",
        headers=auth_headers,
        json={"pin_min_interval_minutes": 0},
    )
    assert r.status_code == 422

    r = client.put(
        f"/api/nick-lives/{owned_nick}/settings",
        headers=auth_headers,
        json={"pin_max_interval_minutes": 61},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_auto_pin_start_requires_ownership(client, auth_headers, foreign_nick):
    r = client.post(
        f"/api/nick-lives/{foreign_nick}/auto-pin/start",
        headers=auth_headers,
        json={"session_id": 1234},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_auto_pin_stop_requires_ownership(client, auth_headers, foreign_nick):
    r = client.post(
        f"/api/nick-lives/{foreign_nick}/auto-pin/stop",
        headers=auth_headers,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_auto_pin_status_reports_running(client, auth_headers, owned_nick):
    with patch("app.main.auto_pinner") as mock_pinner:
        mock_pinner.is_running.return_value = True
        r = client.get(
            f"/api/nick-lives/{owned_nick}/auto-pin/status",
            headers=auth_headers,
        )
    assert r.status_code == 200
    assert r.json() == {"running": True}
```

> **Note:** `client`, `auth_headers`, `owned_nick`, `foreign_nick` fixtures should already exist in `backend/tests/conftest.py` (used by `test_auth_router.py`, `test_admin_router.py`, etc.). If any fixture name differs in this repo, match the existing fixture names. If a needed fixture doesn't exist, extend `conftest.py` minimally — do NOT rewrite existing fixtures.

- [ ] **Step 5: Run router tests**

```bash
cd backend && pytest tests/test_auto_pin_router.py -v
```

Expected: `5 passed` (after fixture names match). If fixture errors appear, inspect `conftest.py` and adjust fixture names in the test file accordingly.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/nick_live.py backend/tests/test_auto_pin_router.py
git commit -m "feat(api): add /auto-pin/start|stop|status + extend PUT settings"
```

---

## Task 7: Lifecycle Wiring (main.py + admin.py)

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/routers/admin.py`

- [ ] **Step 1: Declare `auto_pinner` module-level reference**

Edit `backend/app/main.py`. After the existing `auto_poster: "AutoPoster | None" = None` declaration (around line 27), add:

```python
auto_pinner: "AutoPinner | None" = None  # noqa: F821
```

- [ ] **Step 2: Initialise `auto_pinner` in `lifespan`**

In `backend/app/main.py`, inside the `lifespan()` function, after the `auto_poster = AutoPoster(moderator)` line (around line 66), add:

```python
    from app.services.auto_pinner import AutoPinner
    global auto_pinner
    auto_pinner = AutoPinner()
```

- [ ] **Step 3: Stop `auto_pinner` on shutdown**

In the same `lifespan()` `finally:` block, after the `if auto_poster is not None: auto_poster.stop_all()` block, add:

```python
        if auto_pinner is not None:
            auto_pinner.stop_all()
```

- [ ] **Step 4: Call `auto_pinner.stop_user_nicks` on admin lock + delete**

Edit `backend/app/routers/admin.py`. Find the `if body.is_locked is not None:` block (around line 85). Expand it so both pinner and poster are stopped on lock, both started on unlock:

```python
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
```

Then find the `delete_user` endpoint (around line 96). Update the cleanup try block (around line 112–122):

```python
    from app.main import auto_poster, auto_pinner
    from app.services.live_moderator import moderator
    import logging as _logging
    try:
        if auto_poster is not None:
            auto_poster.stop_user_nicks(u.id)
        if auto_pinner is not None:
            auto_pinner.stop_user_nicks(u.id)
        moderator.drop_user(u.id)
    except Exception as exc:
        _logging.getLogger(__name__).warning(
            "Side-effect cleanup failed on user delete; continuing: %s", exc
        )
```

- [ ] **Step 5: Smoke-boot the app**

```bash
cd backend && python -c "
import asyncio
from app.main import app, lifespan
async def boot():
    async with lifespan(app):
        from app.main import auto_pinner
        assert auto_pinner is not None
        print('auto_pinner initialised OK')
asyncio.run(boot())
"
```

Expected: `auto_pinner initialised OK` (no stack trace).

- [ ] **Step 6: Run full backend test suite**

```bash
cd backend && pytest -x -q
```

Expected: all tests pass (or at minimum: pre-existing passing tests stay passing; new auto-pin tests pass).

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/app/routers/admin.py
git commit -m "feat(lifecycle): init AutoPinner in lifespan + stop on admin lock/delete"
```

---

## Task 8: Frontend — API client

**Files:**
- Modify: `frontend/src/` (locate auto-post API file and colocate)

- [ ] **Step 1: Locate existing auto-post client**

```bash
cd frontend && grep -rn "auto-post/start\|startAutoPost\|auto_post/start" src/
```

Note the file path — likely `src/api/nickLive.ts` or similar. Call it `<api-file>` below.

- [ ] **Step 2: Add 3 auto-pin functions**

Edit `<api-file>`. Next to the existing auto-post functions, add (adjust import/call style to match surrounding code — e.g. `fetch` with base URL, `axios` instance, or `apiClient.post`):

```ts
export async function startAutoPin(nickLiveId: number, sessionId: number) {
  return apiClient.post(`/api/nick-lives/${nickLiveId}/auto-pin/start`, {
    session_id: sessionId,
  });
}

export async function stopAutoPin(nickLiveId: number) {
  return apiClient.post(`/api/nick-lives/${nickLiveId}/auto-pin/stop`);
}

export async function getAutoPinStatus(nickLiveId: number): Promise<{ running: boolean }> {
  const { data } = await apiClient.get(`/api/nick-lives/${nickLiveId}/auto-pin/status`);
  return data;
}
```

Replace `apiClient` with whatever the existing auto-post functions use in the same file.

- [ ] **Step 3: Commit**

```bash
git add frontend/src
git commit -m "feat(fe): add auto-pin API client (start/stop/status)"
```

---

## Task 9: Frontend — `NickConfigModal` section

**Files:**
- Modify: `frontend/src/components/NickConfigModal.tsx`

- [ ] **Step 1: Add local state + polling for pin**

Open `frontend/src/components/NickConfigModal.tsx`. Near existing auto-post state (search `auto_post_enabled` in the file), add parallel pin state. Inside the component, alongside the auto-post useState hooks:

```tsx
const [autoPinEnabled, setAutoPinEnabled] = useState<boolean>(
  nickSettings?.auto_pin_enabled ?? false
);
const [pinMinMinutes, setPinMinMinutes] = useState<number>(
  nickSettings?.pin_min_interval_minutes ?? 2
);
const [pinMaxMinutes, setPinMaxMinutes] = useState<number>(
  nickSettings?.pin_max_interval_minutes ?? 5
);
const [pinRunning, setPinRunning] = useState<boolean>(false);
const [pinError, setPinError] = useState<string | null>(null);
```

(Adjust `nickSettings` to whatever prop/hook already supplies settings in this component.)

- [ ] **Step 2: Poll status while modal open**

Add a `useEffect` that mirrors the auto-post polling pattern already in the file (search `auto-post/status` or `getAutoPostStatus` — copy its structure):

```tsx
useEffect(() => {
  let cancelled = false;
  const tick = async () => {
    try {
      const s = await getAutoPinStatus(nickLiveId);
      if (!cancelled) setPinRunning(s.running);
    } catch { /* ignore */ }
  };
  tick();
  const id = setInterval(tick, 5000);
  return () => { cancelled = true; clearInterval(id); };
}, [nickLiveId]);
```

Import `getAutoPinStatus` from the file edited in Task 8.

- [ ] **Step 3: Persist on toggle/input change**

Extend the existing settings-save handler (search `auto_post_enabled:` inside a PUT/PATCH body in this file). Add the 3 pin fields to the body alongside existing auto-post fields:

```tsx
{
  // ...existing fields...
  auto_pin_enabled: autoPinEnabled,
  pin_min_interval_minutes: pinMinMinutes,
  pin_max_interval_minutes: pinMaxMinutes,
}
```

- [ ] **Step 4: Render the Auto-Pin section**

In the JSX, below the Auto Post section, add:

```tsx
<section className="auto-pin-section">
  <h4>Auto Pin sản phẩm</h4>

  <label>
    <input
      type="checkbox"
      checked={autoPinEnabled}
      onChange={(e) => setAutoPinEnabled(e.target.checked)}
    />
    Bật tự động pin sản phẩm
  </label>

  <div className="pin-interval">
    <label>
      Min:
      <input
        type="number"
        min={1}
        max={60}
        value={pinMinMinutes}
        onChange={(e) => setPinMinMinutes(Number(e.target.value))}
      />
      phút
    </label>
    <label>
      Max:
      <input
        type="number"
        min={1}
        max={60}
        value={pinMaxMinutes}
        onChange={(e) => setPinMaxMinutes(Number(e.target.value))}
      />
      phút
    </label>
  </div>

  {pinMinMinutes > pinMaxMinutes && (
    <p className="error">Min phải nhỏ hơn hoặc bằng Max</p>
  )}

  <p>Trạng thái: {pinRunning ? "● Đang chạy" : "○ Đã dừng"}</p>

  <button
    type="button"
    disabled={!autoPinEnabled || pinRunning || pinMinMinutes > pinMaxMinutes}
    onClick={async () => {
      setPinError(null);
      try {
        await startAutoPin(nickLiveId, currentSessionId);
        setPinRunning(true);
      } catch (e: any) {
        setPinError(e?.response?.data?.detail ?? "Start Pin thất bại");
      }
    }}
  >
    Bắt đầu Pin
  </button>

  <button
    type="button"
    disabled={!pinRunning}
    onClick={async () => {
      await stopAutoPin(nickLiveId);
      setPinRunning(false);
    }}
  >
    Dừng Pin
  </button>

  {pinError && <p className="error">{pinError}</p>}
</section>
```

Adjust class names / styling to match existing component conventions. `currentSessionId` should be the same variable used by the auto-post Start button in this file (search `session_id` or `sessionId` near the auto-post start call). If component doesn't yet receive it, lift from the same prop auto-post uses.

- [ ] **Step 5: Import the API functions**

At the top of the file, add imports matching your API file layout:

```tsx
import { startAutoPin, stopAutoPin, getAutoPinStatus } from "../api/...";
```

- [ ] **Step 6: Build check**

```bash
cd frontend && pnpm build
```

Expected: build succeeds. If it uses npm/yarn, use the project's actual command (check `package.json` scripts).

- [ ] **Step 7: Manual smoke test**

1. Start backend: `cd backend && python run.py`
2. Start frontend: `cd frontend && pnpm dev`
3. Log in, open a nick in `NickConfigModal`.
4. Tick "Bật tự động pin sản phẩm", set Min=1 Max=1, Save.
5. Click "Bắt đầu Pin" — status should flip to "● Đang chạy" within 5s.
6. Wait ~60s — check backend log for line `Auto-pin nick=<id> item=<iid> shop=<sid>` or error.
7. Click "Dừng Pin" — status flips to "○ Đã dừng".

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/NickConfigModal.tsx
git commit -m "feat(fe): add Auto Pin sản phẩm section to NickConfigModal"
```

---

## Task 10: Final Verification

- [ ] **Step 1: Run full backend test suite**

```bash
cd backend && pytest -q
```

Expected: all green.

- [ ] **Step 2: Run frontend build**

```bash
cd frontend && pnpm build
```

Expected: success.

- [ ] **Step 3: Verify git log matches expected commits**

```bash
git log --oneline -12
```

Expected (order may vary slightly by task sequencing):

```
feat(fe): add Auto Pin sản phẩm section to NickConfigModal
feat(fe): add auto-pin API client (start/stop/status)
feat(lifecycle): init AutoPinner in lifespan + stop on admin lock/delete
feat(api): add /auto-pin/start|stop|status + extend PUT settings
feat(settings): persist auto-pin fields via update_nick_settings
feat(auto-pin): add AutoPinner service with random in-stock pick loop
feat(relive): add pin_livestream_item for POST /livestream/show
feat(schema): add auto-pin fields + AutoPinStartRequest
feat(db): add auto-pin columns to nick_live_settings
docs: add auto-pin random product design spec
```

- [ ] **Step 4: Update GitNexus index**

```bash
npx gitnexus analyze
```

Expected: index refresh completes. If embeddings were present, use `npx gitnexus analyze --embeddings`.

- [ ] **Step 5: Done**

Feature Auto Pin Random Product hoàn tất. Config per nick trong `NickConfigModal`, loop đóng gói trong `AutoPinner`, full TDD coverage cho service + router.
