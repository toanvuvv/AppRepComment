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
