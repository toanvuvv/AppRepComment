# backend/tests/test_concurrent_scanner.py
"""
Concurrent multi-nick scanner behavior tests.

These tests assert behavior (not implementation) of CommentScanner so they
remain green across Wave 2 refactors. Tests that document known races or
performance issues are marked xfail with the tracking code (H1-H8).

Run: cd backend && pytest tests/test_concurrent_scanner.py -v
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def scanner_fixture():
    """Yields the singleton scanner and force-cancels any tasks on teardown."""
    from app.services.comment_scanner import scanner

    # Clean slate in case prior test leaked state.
    for nick_id in list(scanner._tasks.keys()):
        task = scanner._tasks.get(nick_id)
        if task and not task.done():
            task.cancel()
    scanner._tasks.clear()
    scanner._comments.clear()
    scanner._seen_ids.clear()
    scanner._session_ids.clear()
    scanner._new_comments.clear()

    yield scanner

    # Teardown: cancel any remaining tasks.
    for nick_id in list(scanner._tasks.keys()):
        task = scanner._tasks.get(nick_id)
        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

    scanner._tasks.clear()
    scanner._comments.clear()
    scanner._seen_ids.clear()
    scanner._session_ids.clear()
    scanner._new_comments.clear()


SideEffect = Callable[[str, int, int], list[dict[str, Any]]]


@pytest.fixture
def patch_get_comments(monkeypatch):
    """
    Patch `get_comments` as imported into comment_scanner.

    Accepts a callable (cookies, session_id, last_ts) -> list[dict].
    Returns the AsyncMock so the caller can inspect call counts.
    """

    def _apply(side_effect: SideEffect) -> AsyncMock:
        mock = AsyncMock(side_effect=side_effect)
        # The scanner imports the symbol directly:
        # `from app.services.shopee_api import get_comments`.
        # Patch the binding in the scanner module.
        monkeypatch.setattr("app.services.comment_scanner.get_comments", mock)
        # Also patch at the source for belt-and-braces.
        monkeypatch.setattr("app.services.shopee_api.get_comments", mock)
        return mock

    return _apply


@pytest.fixture
def disable_auto_reply(monkeypatch):
    """Short-circuit the auto-reply path so tests don't touch DB/LLM."""

    async def _noop(self, nick_live_id, session_id, comments):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(
        "app.services.comment_scanner.CommentScanner._process_auto_reply",
        _noop,
    )


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _comment(cid: str | int, text: str = "hi", username: str = "u") -> dict:
    return {"id": str(cid), "content": text, "username": username, "timestamp": int(time.time())}


async def _wait_for(condition, timeout: float = 4.0, interval: float = 0.05) -> bool:
    """Poll `condition` (sync or async) until it returns True or timeout elapses."""
    import inspect
    deadline = time.monotonic() + timeout
    async def _check():
        r = condition()
        if inspect.isawaitable(r):
            r = await r
        return bool(r)
    while time.monotonic() < deadline:
        if await _check():
            return True
        await asyncio.sleep(interval)
    return await _check()


# ----------------------------------------------------------------------------
# 1. Independent scanning per nick
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_nicks_scan_independently(
    scanner_fixture, patch_get_comments, disable_auto_reply
):
    """Three concurrent nicks receive their own comments only."""
    scanner = scanner_fixture

    # Map session_id -> comment id pool.
    per_session = {
        1001: ["a1", "a2", "a3"],
        1002: ["b1", "b2", "b3"],
        1003: ["c1", "c2", "c3"],
    }

    async def side_effect(cookies, session_id, last_ts):
        ids = per_session.get(session_id, [])
        return [_comment(cid, text=f"msg-{cid}") for cid in ids]

    patch_get_comments(side_effect)

    scanner.start(nick_live_id=1, session_id=1001, cookies="ck1", poll_interval=0.1)
    scanner.start(nick_live_id=2, session_id=1002, cookies="ck2", poll_interval=0.1)
    scanner.start(nick_live_id=3, session_id=1003, cookies="ck3", poll_interval=0.1)

    async def all_have_three() -> bool:
        return (
            len(scanner.get_comments(1)) == 3
            and len(scanner.get_comments(2)) == 3
            and len(scanner.get_comments(3)) == 3
        )

    assert await _wait_for(all_have_three, timeout=3.0)

    ids_1 = {c["id"] for c in scanner.get_comments(1)}
    ids_2 = {c["id"] for c in scanner.get_comments(2)}
    ids_3 = {c["id"] for c in scanner.get_comments(3)}

    assert ids_1 == {"a1", "a2", "a3"}
    assert ids_2 == {"b1", "b2", "b3"}
    assert ids_3 == {"c1", "c2", "c3"}
    assert ids_1.isdisjoint(ids_2)
    assert ids_2.isdisjoint(ids_3)

    scanner.stop(1)
    scanner.stop(2)
    scanner.stop(3)
    await asyncio.sleep(0.2)

    assert scanner.is_scanning(1) is False
    assert scanner.is_scanning(2) is False
    assert scanner.is_scanning(3) is False


# ----------------------------------------------------------------------------
# 2. Dedup
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_prevents_duplicate_processing(
    scanner_fixture, patch_get_comments, disable_auto_reply
):
    """The same comment id returned repeatedly is stored exactly once."""
    scanner = scanner_fixture

    async def side_effect(cookies, session_id, last_ts):
        return [_comment("dup-1", text="hello")]

    mock = patch_get_comments(side_effect)

    scanner.start(nick_live_id=42, session_id=500, cookies="ck", poll_interval=0.1)

    # Wait until the mock has been polled several times.
    await _wait_for(lambda: mock.await_count >= 5, timeout=3.0)

    scanner.stop(42)
    await asyncio.sleep(0.15)

    stored = scanner.get_comments(42)
    assert len(stored) == 1, f"Expected single dedup'd comment, got {len(stored)}"
    assert stored[0]["id"] == "dup-1"


# ----------------------------------------------------------------------------
# 3. Stopping one nick does not affect others
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_one_nick_does_not_affect_others(
    scanner_fixture, patch_get_comments, disable_auto_reply
):
    scanner = scanner_fixture

    counters: dict[int, int] = {1: 0, 2: 0}

    async def side_effect(cookies, session_id, last_ts):
        # session 100 -> nick 1, session 200 -> nick 2
        nick = 1 if session_id == 100 else 2
        counters[nick] += 1
        return [_comment(f"{nick}-{counters[nick]}")]

    patch_get_comments(side_effect)

    scanner.start(nick_live_id=1, session_id=100, cookies="ck1", poll_interval=0.1)
    scanner.start(nick_live_id=2, session_id=200, cookies="ck2", poll_interval=0.1)

    async def both_have_some() -> bool:
        return len(scanner.get_comments(1)) >= 1 and len(scanner.get_comments(2)) >= 1

    assert await _wait_for(both_have_some, timeout=3.0)

    scanner.stop(1)
    await asyncio.sleep(0.2)
    count_1_at_stop = len(scanner.get_comments(1))
    count_2_at_stop = len(scanner.get_comments(2))

    # Let nick 2 continue polling for a while.
    await asyncio.sleep(0.8)

    assert scanner.is_scanning(1) is False
    assert scanner.is_scanning(2) is True
    assert len(scanner.get_comments(1)) == count_1_at_stop, "nick 1 should freeze after stop"
    assert len(scanner.get_comments(2)) > count_2_at_stop, "nick 2 should keep growing"

    scanner.stop(2)


# ----------------------------------------------------------------------------
# 4. Rapid start/stop cycles leave no orphans
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rapid_start_stop_cycles(
    scanner_fixture, patch_get_comments, disable_auto_reply
):
    scanner = scanner_fixture

    async def side_effect(cookies, session_id, last_ts):
        return []

    patch_get_comments(side_effect)

    baseline_tasks = len(asyncio.all_tasks())

    for _ in range(5):
        scanner.start(nick_live_id=1, session_id=1, cookies="ck", poll_interval=0.1)
        await asyncio.sleep(0.05)
        scanner.stop(1)
        await asyncio.sleep(0.05)

    # Final settle.
    await asyncio.sleep(0.4)

    assert scanner.is_scanning(1) is False
    assert 1 not in scanner._tasks
    assert 1 not in scanner._session_ids

    current_tasks = len(asyncio.all_tasks())
    # Allow tiny drift (the current test task itself, event loop internals).
    assert current_tasks <= baseline_tasks + 1, (
        f"Orphan tasks: baseline={baseline_tasks}, now={current_tasks}"
    )


# ----------------------------------------------------------------------------
# 5. Concurrent start() on the same nick should yield a single task
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_start_same_nick(
    scanner_fixture, patch_get_comments, disable_auto_reply
):
    scanner = scanner_fixture

    async def side_effect(cookies, session_id, last_ts):
        await asyncio.sleep(0.01)
        return []

    mock = patch_get_comments(side_effect)

    async def call_start():
        scanner.start(nick_live_id=7, session_id=777, cookies="ck", poll_interval=0.2)

    # Fire two concurrent start calls.
    await asyncio.gather(call_start(), call_start())

    # Give either race winner time to settle.
    await asyncio.sleep(0.05)

    assert len(scanner._tasks) == 1
    assert 7 in scanner._tasks

    # Over ~0.5s at poll_interval=0.2, we expect ~2-3 calls, not double.
    before = mock.await_count
    await asyncio.sleep(0.5)
    calls = mock.await_count - before

    assert calls <= 4, f"Too many polls ({calls}) — suggests duplicate task running"

    scanner.stop(7)


# ----------------------------------------------------------------------------
# 6. Auto-reply must not block polling
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_reply_does_not_block_polling(
    scanner_fixture, patch_get_comments, monkeypatch
):
    scanner = scanner_fixture

    # --- Phase 1: baseline with no auto-reply work (moderator not configured). ---
    async def side_effect(cookies, session_id, last_ts):
        return [_comment(f"c-{time.time_ns()}-{i}") for i in range(5)]

    mock = patch_get_comments(side_effect)

    # Make has_config return False so _process_auto_reply short-circuits fast.
    monkeypatch.setattr(
        "app.services.live_moderator.moderator.has_config",
        lambda self_or_nick, *a, **kw: False,
        raising=False,
    )
    # Also stub settings/db to avoid any DB churn regardless of code path.
    async def _noop(self, nick_live_id, session_id, comments):  # type: ignore[no-untyped-def]
        return None

    baseline_noop = _noop
    monkeypatch.setattr(
        "app.services.comment_scanner.CommentScanner._process_auto_reply",
        baseline_noop,
    )

    poll_interval = 0.1
    observation_window = 2.0

    scanner.start(nick_live_id=10, session_id=900, cookies="ck", poll_interval=poll_interval)
    start_calls = mock.await_count
    await asyncio.sleep(observation_window)
    baseline_polls = mock.await_count - start_calls
    scanner.stop(10)
    await asyncio.sleep(0.15)

    expected_polls = observation_window / poll_interval
    # Baseline should be within 50% of expected.
    assert baseline_polls >= expected_polls * 0.5, (
        f"Even baseline is too slow: {baseline_polls} polls in {observation_window}s"
    )

    # --- Phase 2: swap in a slow auto-reply path. ---
    async def slow_reply(self, nick_live_id, session_id, comments):  # type: ignore[no-untyped-def]
        await asyncio.sleep(3.0)

    monkeypatch.setattr(
        "app.services.comment_scanner.CommentScanner._process_auto_reply",
        slow_reply,
    )

    scanner.start(nick_live_id=11, session_id=901, cookies="ck", poll_interval=poll_interval)
    start_calls = mock.await_count
    await asyncio.sleep(observation_window)
    slow_polls = mock.await_count - start_calls
    scanner.stop(11)
    await asyncio.sleep(0.15)

    # If auto-reply blocks polling, slow_polls << baseline_polls.
    # Passing this test means polling kept up (i.e. reply is dispatched off-loop).
    assert slow_polls >= baseline_polls * 0.7, (
        f"Polling blocked by slow reply: baseline={baseline_polls}, slow={slow_polls}"
    )


# ----------------------------------------------------------------------------
# 7. Per-nick queue isolation
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_isolation_between_nicks(
    scanner_fixture, patch_get_comments, disable_auto_reply
):
    scanner = scanner_fixture

    async def side_effect(cookies, session_id, last_ts):
        # Only nick 1 (session 111) emits comments.
        if session_id == 111:
            return [_comment(f"only1-{time.time_ns()}")]
        return []

    patch_get_comments(side_effect)

    # Pre-create queues so both nicks are subscribed.
    q1 = scanner.get_queue(1)
    q2 = scanner.get_queue(2)

    scanner.start(nick_live_id=1, session_id=111, cookies="ck1", poll_interval=0.1)
    scanner.start(nick_live_id=2, session_id=222, cookies="ck2", poll_interval=0.1)

    async def q1_has_items() -> bool:
        return q1.qsize() >= 2

    assert await _wait_for(q1_has_items, timeout=3.0)
    assert q2.qsize() == 0, "nick 2 queue should not have received any comments"

    # Drain q1 and sanity-check payload shape.
    drained = []
    while not q1.empty():
        item = q1.get_nowait()
        if item is None:
            break
        drained.append(item)
    assert all(c["id"].startswith("only1-") for c in drained)

    scanner.stop(1)
    scanner.stop(2)
