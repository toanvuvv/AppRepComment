import os

from fastapi import Depends, HTTPException, Query, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.auth import decode_access_token

# --- Legacy API key (deprecated, removed in Task 12) ---
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_APP_API_KEY = os.getenv("APP_API_KEY", "")


def require_api_key(
    key: str | None = Security(_api_key_header),
    api_key_query: str | None = Query(None, alias="api_key"),
) -> None:
    if not _APP_API_KEY:
        return
    provided = key or api_key_query
    if provided != _APP_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")


# --- JWT auth ---
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: str | None = Query(None),
    db: Session = Depends(get_db),
) -> User:
    raw: str | None = None
    if creds and creds.scheme.lower() == "bearer":
        raw = creds.credentials
    elif token:
        raw = token
    if not raw:
        raise HTTPException(status_code=401, detail="Missing auth token")

    payload = decode_access_token(raw)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Malformed token")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    if user.is_locked:
        raise HTTPException(status_code=403, detail="Account is locked")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user
