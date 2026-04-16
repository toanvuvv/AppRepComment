"""Lazy-initialized shared httpx.AsyncClient.

FastAPI runs as a single event loop per worker process, so a module-level
singleton is safe. The client is created on first use and closed on
application shutdown via `close_client()`.
"""
from __future__ import annotations

import logging

import httpx

from app.config import HTTP_TIMEOUT_SEC

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Return the shared AsyncClient, creating it on first call."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_SEC,
            limits=httpx.Limits(
                max_connections=50,
                max_keepalive_connections=20,
            ),
        )
        logger.info("Created shared httpx.AsyncClient")
    return _client


async def close_client() -> None:
    """Close the shared client and clear the reference."""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception as e:
            logger.warning(f"Error closing shared httpx client: {e}")
        finally:
            _client = None
            logger.info("Closed shared httpx.AsyncClient")
