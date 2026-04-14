import os

from fastapi import HTTPException, Query, Security
from fastapi.security.api_key import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_APP_API_KEY = os.getenv("APP_API_KEY", "")


def require_api_key(
    key: str | None = Security(_api_key_header),
    api_key_query: str | None = Query(None, alias="api_key"),
) -> None:
    """Require API key via header or query param. Skipped if APP_API_KEY env var is not set (dev mode).

    Query param fallback is needed for SSE (EventSource cannot set custom headers).
    """
    if not _APP_API_KEY:
        return  # dev mode: no key configured → open access on localhost
    provided = key or api_key_query
    if provided != _APP_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
