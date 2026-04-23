from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_admin
from app.models.nick_live import NickLive
from app.models.user import User
from app.schemas.settings import (
    SystemKeysResponse,
    SystemOpenAIUpdate,
    SystemReliveUpdate,
)
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.auth import hash_password
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api/admin", tags=["admin"])


class _UserWithCount(UserOut):
    nick_count: int


@router.get("/users", response_model=list[_UserWithCount])
def list_users(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(User, func.count(NickLive.id))
        .outerjoin(NickLive, NickLive.user_id == User.id)
        .group_by(User.id)
        .all()
    )
    return [
        _UserWithCount(**UserOut.model_validate(u).model_dump(), nick_count=int(c))
        for u, c in rows
    ]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="Username already exists")
    u = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role="user",
        max_nicks=body.max_nicks,
        is_locked=False,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return UserOut.model_validate(u)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    changed = False
    if body.max_nicks is not None:
        u.max_nicks = body.max_nicks
        changed = True
    if body.is_locked is not None:
        if u.id == admin.id:
            raise HTTPException(status_code=400, detail="Cannot lock yourself")
        u.is_locked = body.is_locked
        changed = True
    if body.new_password is not None:
        u.password_hash = hash_password(body.new_password)
        changed = True
    if not changed:
        raise HTTPException(status_code=400, detail="No fields to update")
    db.commit()
    db.refresh(u)

    if body.is_locked is not None:
        from app.main import auto_poster, auto_pinner
        if body.is_locked:
            if auto_poster is not None:
                auto_poster.stop_user_nicks(u.id)
            if auto_pinner is not None:
                auto_pinner.stop_user_nicks(u.id)
        else:
            if auto_poster is not None:
                auto_poster.start_user_nicks(u.id)
            if auto_pinner is not None:
                auto_pinner.start_user_nicks(u.id)

    return UserOut.model_validate(u)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if u.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    if u.role == "admin":
        remaining = db.query(User).filter(User.role == "admin", User.id != u.id).count()
        if remaining == 0:
            raise HTTPException(status_code=400, detail="Cannot delete last admin")

    from app.main import auto_poster, auto_pinner
    from app.services.live_moderator import moderator
    import logging as _logging
    try:
        if auto_poster is not None:
            auto_poster.stop_user_nicks(u.id)
        if auto_pinner is not None:
            auto_pinner.stop_user_nicks(u.id)
        moderator.drop_user(u.id)
    except Exception as exc:
        _logging.getLogger(__name__).warning(
            "Side-effect cleanup failed on user delete; continuing: %s", exc
        )

    db.delete(u)
    db.commit()
    return Response(status_code=204)


def _invalidate_all_nick_settings() -> None:
    from app.services.nick_cache import nick_cache
    nick_cache._settings.clear()


@router.get("/system-keys", response_model=SystemKeysResponse)
def get_system_keys(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SystemKeysResponse:
    svc = SettingsService(db)
    return SystemKeysResponse(
        relive_api_key_set=bool(svc.get_system_relive_api_key()),
        openai_api_key_set=bool(svc.get_system_openai_api_key()),
        openai_model=svc.get_system_openai_model(),
    )


@router.put("/system-keys/relive")
def put_system_relive(
    body: SystemReliveUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    SettingsService(db).set_system_relive_api_key(body.api_key)
    _invalidate_all_nick_settings()
    return {"status": "saved"}


@router.put("/system-keys/openai")
def put_system_openai(
    body: SystemOpenAIUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    svc = SettingsService(db)
    svc.set_system_openai_api_key(body.api_key)
    svc.set_system_openai_model(body.model)
    _invalidate_all_nick_settings()
    return {"status": "saved"}
