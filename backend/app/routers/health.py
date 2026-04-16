"""Operational health / monitoring endpoints.

Exposes per-nick runtime state aggregated from the scanner, dispatcher,
rate limiter, reply cache, and (optionally) the circuit registry. Intended
to power a 20-nick dashboard.

Security: all routes require the app API key via ``Depends(require_api_key)``.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

from app.config import REPLY_CACHE_MAX_ENTRIES, REPLY_CONCURRENCY, SHOPEE_BURST, SHOPEE_RATE_PER_SEC
from app.dependencies import require_api_key
from app.services.comment_scanner import scanner
from app.services.reply_dispatcher import dispatcher

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/health",
    tags=["health"],
    dependencies=[Depends(require_api_key)],
)


def _count_active_nicks() -> int:
    """Count scanner tasks that are still running."""
    count = 0
    for task in scanner._tasks.values():
        if task is not None and not task.done():
            count += 1
    return count


def _total_comments_in_memory() -> int:
    """Sum of buffered comment deque lengths across all nicks."""
    total = 0
    for dq in scanner._comments.values():
        try:
            total += len(dq)
        except TypeError:
            continue
    return total


def _llm_in_flight() -> int:
    """Best-effort count of in-flight LLM calls.

    Reads ``asyncio.Semaphore._value`` (internal: remaining slots) and
    subtracts from the configured max. Approximate — may race with
    concurrent acquire/release.
    """
    try:
        remaining = dispatcher._llm_semaphore._value  # type: ignore[attr-defined]
        return max(0, REPLY_CONCURRENCY - int(remaining))
    except Exception:
        return 0


def _shopee_tokens_available() -> float | None:
    """Best-effort read of the token bucket's current token count.

    No lock held — value is approximate.
    """
    try:
        from app.services.rate_limiter import shopee_limiter

        return float(shopee_limiter._tokens)  # type: ignore[attr-defined]
    except Exception:
        return None


def _reply_cache_size() -> int | None:
    """Size of the short-TTL reply cache, if available."""
    try:
        from app.services.reply_cache import reply_cache

        return int(reply_cache.size())
    except Exception:
        return None


def _circuit_state(nick_live_id: int) -> str | None:
    """String state of the per-nick circuit breaker, if the registry exists."""
    try:
        from app.services.circuit_breaker import circuit_registry  # type: ignore

        return str(circuit_registry.for_nick(nick_live_id).state().value)
    except Exception:
        return None


def _sse_subscriber_count(nick_live_id: int) -> int:
    """Size of the SSE subscriber set, tolerant of attribute renames."""
    for attr in ("_subscribers", "_new_comments"):
        subs_map = getattr(scanner, attr, None)
        if subs_map is None:
            continue
        subs = subs_map.get(nick_live_id)
        if subs is None:
            continue
        try:
            return len(subs)
        except TypeError:
            continue
    return 0


def _comments_buffered(nick_live_id: int) -> int:
    dq = scanner._comments.get(nick_live_id)
    if dq is None:
        return 0
    try:
        return len(dq)
    except TypeError:
        return 0


def _build_per_nick_entry(nick_live_id: int, warnings: list[str]) -> dict[str, Any]:
    entry: dict[str, Any] = {"nick_live_id": nick_live_id}

    try:
        entry["session_id"] = scanner._session_ids.get(nick_live_id)
    except Exception as exc:
        warnings.append(f"session_id unavailable for nick={nick_live_id}: {exc}")
        entry["session_id"] = None

    try:
        entry["is_scanning"] = bool(scanner.is_scanning(nick_live_id))
    except Exception as exc:
        warnings.append(f"is_scanning failed for nick={nick_live_id}: {exc}")
        entry["is_scanning"] = False

    try:
        entry["dispatcher_running"] = bool(dispatcher.is_running(nick_live_id))
    except Exception as exc:
        warnings.append(f"dispatcher_running failed for nick={nick_live_id}: {exc}")
        entry["dispatcher_running"] = False

    try:
        entry["reply_queue_depth"] = int(dispatcher.queue_depth(nick_live_id))
    except Exception as exc:
        warnings.append(f"queue_depth failed for nick={nick_live_id}: {exc}")
        entry["reply_queue_depth"] = 0

    entry["comments_buffered"] = _comments_buffered(nick_live_id)
    entry["sse_subscribers"] = _sse_subscriber_count(nick_live_id)
    entry["circuit_state"] = _circuit_state(nick_live_id)
    return entry


@router.get("/scanner")
def scanner_health() -> dict[str, Any]:
    """Per-nick runtime state for 20-nick dashboard.

    Returns a best-effort snapshot. Any component whose attribute or
    singleton is missing is reported under ``warnings`` rather than
    failing the request.
    """
    warnings: list[str] = []

    try:
        active_nicks = _count_active_nicks()
    except Exception as exc:
        warnings.append(f"active_nicks unavailable: {exc}")
        active_nicks = 0

    try:
        total_comments = _total_comments_in_memory()
    except Exception as exc:
        warnings.append(f"total_comments_in_memory unavailable: {exc}")
        total_comments = 0

    llm_in_flight = _llm_in_flight()
    tokens_available = _shopee_tokens_available()
    if tokens_available is None:
        warnings.append("shopee_rate_limiter tokens unavailable")
    cache_size = _reply_cache_size()
    if cache_size is None:
        warnings.append("reply_cache unavailable")

    nick_ids: set[int] = set()
    try:
        nick_ids |= set(scanner._tasks.keys())
    except Exception as exc:
        warnings.append(f"scanner._tasks keys unavailable: {exc}")
    try:
        nick_ids |= set(dispatcher._queues.keys())
    except Exception as exc:
        warnings.append(f"dispatcher._queues keys unavailable: {exc}")

    per_nick = [_build_per_nick_entry(nid, warnings) for nid in sorted(nick_ids)]

    payload: dict[str, Any] = {
        "active_nicks": active_nicks,
        "total_comments_in_memory": total_comments,
        "llm_concurrency": {
            "max": REPLY_CONCURRENCY,
            "in_flight": llm_in_flight,
        },
        "shopee_rate_limiter": {
            "rate_per_sec": SHOPEE_RATE_PER_SEC,
            "burst": SHOPEE_BURST,
            "tokens_available": tokens_available,
        },
        "reply_cache": {
            "size": cache_size if cache_size is not None else 0,
            "max": REPLY_CACHE_MAX_ENTRIES,
        },
        "per_nick": per_nick,
    }
    if warnings:
        payload["warnings"] = warnings
    return payload


@router.get("/ping")
def ping() -> dict[str, str]:
    """Lightweight liveness probe. Still requires API key (via router dep)."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# NOTE: Register in main.py with:
#   from app.routers.health import router as health_router
#   app.include_router(health_router)
