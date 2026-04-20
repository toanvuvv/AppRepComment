from fastapi import APIRouter, Depends, HTTPException, Request, Response
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.user import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    UserOut,
)
from app.services.auth import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.services import login_attempts

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    ip = get_remote_address(request)

    if login_attempts.is_rate_limited(ip):
        raise HTTPException(status_code=429, detail="Too many attempts, try again later")

    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        login_attempts.record_failure(ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.is_locked:
        login_attempts.record_failure(ip)
        raise HTTPException(status_code=403, detail="Account is locked")

    # Successful login — clear the failure counter for this IP.
    login_attempts.reset(ip)

    token = create_access_token(user_id=user.id, username=user.username, role=user.role)
    return LoginResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.post("/change-password", status_code=204)
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Old password incorrect")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return Response(status_code=204)
