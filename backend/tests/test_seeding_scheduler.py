import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.seeding_scheduler import SeedingRunConfig, SeedingScheduler


@pytest.fixture
def scheduler():
    s = SeedingScheduler()
    yield s
    s.stop_all()


@pytest.mark.asyncio
async def test_start_registers_task(scheduler):
    cfg = SeedingRunConfig(
        log_session_id=1, user_id=1, nick_live_id=1,
        shopee_session_id=100, clone_ids=(1,),
        min_interval_sec=30, max_interval_sec=60,
    )

    async def never_done(*a, **kw):
        await asyncio.sleep(60)

    with patch.object(scheduler, "_loop", new=AsyncMock(side_effect=never_done)):
        scheduler.start(cfg)
        assert scheduler.is_running(1)


@pytest.mark.asyncio
async def test_start_rejects_duplicate(scheduler):
    cfg = SeedingRunConfig(
        log_session_id=1, user_id=1, nick_live_id=1,
        shopee_session_id=100, clone_ids=(1,),
        min_interval_sec=30, max_interval_sec=60,
    )

    async def never_done(*a, **kw):
        await asyncio.sleep(60)

    with patch.object(scheduler, "_loop", new=AsyncMock(side_effect=never_done)):
        scheduler.start(cfg)
        with pytest.raises(ValueError):
            scheduler.start(cfg)


@pytest.mark.asyncio
async def test_stop_cancels(scheduler):
    cfg = SeedingRunConfig(
        log_session_id=1, user_id=1, nick_live_id=1,
        shopee_session_id=100, clone_ids=(1,),
        min_interval_sec=30, max_interval_sec=60,
    )

    async def never_done(*a, **kw):
        await asyncio.sleep(60)

    with patch.object(scheduler, "_loop", new=AsyncMock(side_effect=never_done)):
        scheduler.start(cfg)
        await scheduler.stop(1)
    assert not scheduler.is_running(1)


@pytest.mark.asyncio
async def test_loop_picks_random_clone_and_template(monkeypatch):
    scheduler = SeedingScheduler()
    calls = []

    async def fake_send(**kw):
        calls.append(kw)

    monkeypatch.setattr("app.services.seeding_scheduler.seeding_sender.send",
                        AsyncMock(side_effect=fake_send))

    fake_templates = [MagicMock(id=10, enabled=True, content="a"),
                      MagicMock(id=11, enabled=True, content="b")]
    fake_clones = [MagicMock(id=1, last_sent_at=None),
                   MagicMock(id=2, last_sent_at=None)]

    monkeypatch.setattr(scheduler, "_load_templates", lambda uid: fake_templates)
    monkeypatch.setattr(scheduler, "_load_clones", lambda ids: fake_clones)
    monkeypatch.setattr("app.services.seeding_scheduler.asyncio.sleep",
                        AsyncMock(return_value=None))

    cfg = SeedingRunConfig(
        log_session_id=1, user_id=1, nick_live_id=1,
        shopee_session_id=100, clone_ids=(1, 2),
        min_interval_sec=10, max_interval_sec=10,
    )

    await scheduler._iteration(cfg)

    assert len(calls) == 1
    kw = calls[0]
    assert kw["clone_id"] in (1, 2)
    assert kw["template_id"] in (10, 11)
    assert kw["mode"] == "auto"
    assert kw["shopee_session_id"] == 100


@pytest.mark.asyncio
async def test_loop_no_eligible_clone_writes_rate_limited(monkeypatch):
    from datetime import datetime, timezone
    scheduler = SeedingScheduler()
    writes = []

    monkeypatch.setattr(scheduler, "_load_templates",
                        lambda uid: [MagicMock(id=10, enabled=True, content="a")])
    monkeypatch.setattr(scheduler, "_load_clones",
                        lambda ids: [MagicMock(id=1, last_sent_at=datetime.now(timezone.utc))])
    monkeypatch.setattr(scheduler, "_write_rate_limited_log",
                        lambda **kw: writes.append(kw))
    monkeypatch.setattr("app.services.seeding_scheduler.asyncio.sleep",
                        AsyncMock(return_value=None))

    cfg = SeedingRunConfig(
        log_session_id=1, user_id=1, nick_live_id=1,
        shopee_session_id=100, clone_ids=(1,),
        min_interval_sec=10, max_interval_sec=10,
    )
    await scheduler._iteration(cfg)

    assert len(writes) == 1
    assert writes[0]["clone_id"] == 1


@pytest.mark.asyncio
async def test_loop_no_templates_stops(monkeypatch):
    scheduler = SeedingScheduler()
    monkeypatch.setattr(scheduler, "_load_templates", lambda uid: [])
    monkeypatch.setattr("app.services.seeding_scheduler.asyncio.sleep",
                        AsyncMock(return_value=None))

    cfg = SeedingRunConfig(
        log_session_id=1, user_id=1, nick_live_id=1,
        shopee_session_id=100, clone_ids=(1,),
        min_interval_sec=10, max_interval_sec=10,
    )
    cont = await scheduler._iteration(cfg)
    assert cont is False
