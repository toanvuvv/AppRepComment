"""Fetch host credentials (usersig + uuid) from relive.vn API."""

import json
import logging
from typing import Any

from app.services.http_client import get_client

logger = logging.getLogger(__name__)

_RELIVE_URL = "https://api.relive.vn/livestream/preview"
_RELIVE_ITEMS_URL = "https://api.relive.vn/livestream/items"


async def get_host_credentials(
    cookies: str,
    api_key: str,
    proxy: str | None = None,
) -> dict[str, Any]:
    """Call relive.vn to obtain usersig and uuid for the host.

    Returns {"usersig": str, "uuid": str} on success.
    Raises ValueError on failure with a descriptive message.
    """
    payload: dict[str, Any] = {
        "apikey": api_key,
        "cookie": cookies,
        "country": "vn",
        "proxy": proxy or "",
    }

    client = get_client()
    try:
        resp = await client.post(_RELIVE_URL, json=payload, timeout=30.0)
    except Exception as exc:
        raise ValueError(f"Relive.vn request failed: {exc}") from exc

    if resp.status_code != 200:
        raise ValueError(
            f"Relive.vn returned status {resp.status_code}: {resp.text[:300]}"
        )

    try:
        data = resp.json()
    except Exception as exc:
        raise ValueError(f"Relive.vn returned invalid JSON: {exc}") from exc

    root = data.get("data") or data
    uuid_val = root.get("uuid")
    usersig = None
    # preview_config may be nested: data.data.preview_config or data.preview_config
    inner = root.get("data") if isinstance(root.get("data"), dict) else root
    preview_config = inner.get("preview_config")
    if isinstance(preview_config, dict):
        usersig = preview_config.get("usersig")

    if not uuid_val or not usersig:
        raise ValueError(
            f"Relive.vn response missing uuid or usersig. "
            f"Keys in data: {list(root.keys()) if isinstance(root, dict) else 'N/A'}"
        )

    return {"usersig": usersig, "uuid": uuid_val}


async def fetch_livestream_items(
    api_key: str,
    cookies: str,
    session_id: int,
    proxy: str | None = None,
) -> str:
    """Call relive.vn /livestream/items and return the raw JSON string.

    The returned string is fed directly into KnowledgeProductService.parse_shopee_cart_json.
    """
    payload: dict[str, Any] = {
        "apikey": api_key,
        "cookie": cookies,
        "session_id": session_id,
        "country": "vn",
        "proxy": proxy or "",
    }

    client = get_client()
    try:
        resp = await client.post(_RELIVE_ITEMS_URL, json=payload, timeout=30.0)
    except Exception as exc:
        raise ValueError(f"Relive.vn items request failed: {exc}") from exc

    if resp.status_code != 200:
        raise ValueError(
            f"Relive.vn items returned status {resp.status_code}: {resp.text[:300]}"
        )

    return resp.text


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
