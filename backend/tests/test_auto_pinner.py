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

    monkeypatch.setattr("app.services.auto_pinner._sleep", fast_sleep)
    monkeypatch.setattr(
        "app.services.relive_service.pin_livestream_item", fake_pin
    )

    with patch.object(pinner, "_load_settings", return_value=(settings, 7)), \
         patch.object(pinner, "_load_api_key", return_value="KEY"), \
         patch.object(pinner, "_load_in_stock_products",
                      return_value=[(111, 222)]):
        task = asyncio.create_task(pinner._loop(1, 500, "cookies"))
        for _ in range(5):
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

    monkeypatch.setattr("app.services.auto_pinner._sleep", fast_sleep)
    monkeypatch.setattr(
        "app.services.relive_service.pin_livestream_item", fake_pin
    )

    with patch.object(pinner, "_load_settings", return_value=(settings, 7)), \
         patch.object(pinner, "_load_api_key", return_value="KEY"), \
         patch.object(pinner, "_load_in_stock_products", return_value=[]):
        task = asyncio.create_task(pinner._loop(1, 500, "cookies"))
        for _ in range(5):
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

    monkeypatch.setattr("app.services.auto_pinner._sleep", fast_sleep)
    monkeypatch.setattr(
        "app.services.relive_service.pin_livestream_item", fail_pin
    )

    with patch.object(pinner, "_load_settings", return_value=(settings, 7)), \
         patch.object(pinner, "_load_api_key", return_value="KEY"), \
         patch.object(pinner, "_load_in_stock_products",
                      return_value=[(1, 2)]):
        task = asyncio.create_task(pinner._loop(1, 500, "cookies"))
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def test_load_api_key_reads_system_scope(monkeypatch):
    import importlib
    import sys
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # Reload app.database first so Base has fresh metadata, then reload
    # all model modules so their mappers re-register against the new Base.
    import app.database as _db_mod
    importlib.reload(_db_mod)
    for mod_name in ["app.models.user", "app.models.nick_live", "app.models.settings"]:
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])

    from app.database import Base
    from app.services.settings_service import SettingsService

    mem_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(mem_engine)
    MemSession = sessionmaker(bind=mem_engine, autocommit=False, autoflush=False)

    with MemSession() as db:
        # A rogue per-user row that must be ignored.
        SettingsService(db, user_id=42).set_setting("relive_api_key", "per-user-stale")
        SettingsService(db).set_system_relive_api_key("system-live")

    # Patch SessionLocal inside auto_pinner to use the in-memory session
    import app.services.auto_pinner as _ap_mod
    monkeypatch.setattr(_ap_mod, "SessionLocal", MemSession)

    pinner = AutoPinner()
    assert pinner._load_api_key(42) == "system-live"
