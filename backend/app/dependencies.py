import os

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_APP_API_KEY = os.getenv("APP_API_KEY", "")


def require_api_key(key: str | None = Security(_api_key_header)) -> None:
    """Require X-API-Key header. Skipped if APP_API_KEY env var is not set (dev mode)."""
    if not _APP_API_KEY:
        return  # dev mode: no key configured → open access on localhost
    if key != _APP_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
