"""Shopee Creator API calls.

Uses the shared httpx AsyncClient and the global token-bucket rate limiter.
Maps upstream HTTP status codes onto our domain exception hierarchy so
callers (poll loop, reply dispatcher) can react appropriately without
parsing httpx errors themselves.
"""
from __future__ import annotations

import hashlib
import time

import httpx

from app.services.exceptions import (
    ShopeeAuthError,
    ShopeeRateLimitError,
    ShopeeServerError,
)
from app.services.http_client import get_client
from app.services.rate_limiter import shopee_limiter

_SESSIONS_CACHE: dict[str, tuple[float, dict]] = {}
_SESSIONS_CACHE_TTL = 10.0


def _cookie_key(cookies: str) -> str:
    return hashlib.sha256(cookies.encode("utf-8", errors="ignore")).hexdigest()


def invalidate_sessions_cache(cookies: str) -> None:
    _SESSIONS_CACHE.pop(_cookie_key(cookies), None)


SHOPEE_HEADERS = {
    "accept": "application/json",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/json",
    "language": "en",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "x-env": "live",
    "x-region": "vn",
    "x-region-domain": "vn",
    "x-region-timezone": "+0700",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "referer": "https://creator.shopee.vn/",
}


def _raise_for_shopee(resp: httpx.Response, endpoint: str) -> None:
    """Map upstream status codes onto our exception hierarchy."""
    status = resp.status_code
    if 200 <= status < 300:
        return
    if status in (401, 403):
        raise ShopeeAuthError(
            f"{endpoint}: auth rejected (status={status})"
        )
    if status == 429:
        raise ShopeeRateLimitError(
            f"{endpoint}: rate limited (status={status})"
        )
    if 500 <= status < 600:
        raise ShopeeServerError(
            f"{endpoint}: upstream server error (status={status})"
        )
    # Other 4xx — surface the httpx error so callers can see details.
    resp.raise_for_status()


async def get_live_sessions(cookies: str) -> dict:
    """Fetch session list from Shopee Creator API (10-second in-memory cache)."""
    key = _cookie_key(cookies)
    now = time.monotonic()
    cached = _SESSIONS_CACHE.get(key)
    if cached and now - cached[0] < _SESSIONS_CACHE_TTL:
        return cached[1]

    url = (
        "https://creator.shopee.vn/supply/api/lm/sellercenter/realtime/sessionList"
        "?page=1&pageSize=10&name=&orderBy=&sort="
    )
    headers = {**SHOPEE_HEADERS, "cookie": cookies}

    await shopee_limiter.acquire()
    client = get_client()
    resp = await client.get(url, headers=headers)
    _raise_for_shopee(resp, "get_live_sessions")
    data = resp.json()
    _SESSIONS_CACHE[key] = (now, data)
    return data


async def get_comments(cookies: str, session_id: int, start_timestamp: int) -> list:
    """Fetch comments from a live session."""
    url = (
        "https://creator.shopee.vn/supply/api/lm/sellercenter/realtime/"
        f"dashboard/livestream/comments?sessionId={session_id}"
        f"&startTimestamp={start_timestamp}"
    )
    headers = {**SHOPEE_HEADERS, "cookie": cookies}

    await shopee_limiter.acquire()
    client = get_client()
    resp = await client.get(url, headers=headers)
    _raise_for_shopee(resp, "get_comments")

    data = resp.json()
    items = (
        data.get("data", {}).get("comments")
        or data.get("data", {}).get("list")
        or data.get("data")
        or []
    )
    if not isinstance(items, list):
        items = []
    return items
