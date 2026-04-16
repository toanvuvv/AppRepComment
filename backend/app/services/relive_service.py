"""Fetch host credentials (usersig + uuid) from relive.vn API."""

import logging
from typing import Any

from app.services.http_client import get_client

logger = logging.getLogger(__name__)

_RELIVE_URL = "https://api.relive.vn/livestream/preview"


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
    }
    if proxy:
        payload["proxy"] = proxy

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
    preview_config = root.get("preview_config")
    if isinstance(preview_config, dict):
        usersig = preview_config.get("usersig")

    if not uuid_val or not usersig:
        raise ValueError(
            f"Relive.vn response missing uuid or usersig. "
            f"Keys in data: {list(root.keys()) if isinstance(root, dict) else 'N/A'}"
        )

    return {"usersig": usersig, "uuid": uuid_val}
