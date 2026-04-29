from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.auth import decode_access_token

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


def resolve_user_context(
    as_user_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Return the user whose context the request operates in.

    - ``as_user_id`` omitted or equal to caller → caller (back-compat).
    - Non-admin caller passing a different id → 403.
    - Admin caller passing a non-existent id → 404.
    - Admin caller passing a valid id → that user.
    """
    if as_user_id is None or as_user_id == user.id:
        return user
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    target = db.get(User, as_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target user not found")
    return target
