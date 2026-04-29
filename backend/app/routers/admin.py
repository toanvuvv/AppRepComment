from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_admin
from app.models.nick_live import NickLive
from app.models.seeding import SeedingClone
from app.models.settings import AppSetting, NickLiveSetting
from app.models.user import User
from app.schemas.settings import (
    SystemKeysResponse,
    SystemOpenAIUpdate,
    SystemReliveUpdate,
)
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.auth import hash_password
from app.services.nick_cache import nick_cache
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api/admin", tags=["admin"])


class _UserWithCount(UserOut):
    nick_count: int
    clone_count: int
    live_reply_enabled_count: int
    openai_own_key_set: bool


class _NickDetail(BaseModel):
    id: int
    name: str
    shopee_user_id: int
    reply_mode: str
    reply_enabled: bool
    reply_to_host: bool
    reply_to_moderator: bool
    auto_post_enabled: bool
    auto_pin_enabled: bool


@router.get("/users", response_model=list[_UserWithCount])
def list_users(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = db.query(User).all()

    nick_counts = dict(
        db.query(NickLive.user_id, func.count(NickLive.id))
        .group_by(NickLive.user_id)
        .all()
    )
    clone_counts = dict(
        db.query(SeedingClone.user_id, func.count(SeedingClone.id))
        .group_by(SeedingClone.user_id)
        .all()
    )
    reply_on_counts = dict(
        db.query(NickLive.user_id, func.count(NickLive.id))
        .join(NickLiveSetting, NickLiveSetting.nick_live_id == NickLive.id)
        .filter(NickLiveSetting.reply_mode != "none")
        .group_by(NickLive.user_id)
        .all()
    )
    own_key_user_ids = {
        uid for (uid,) in db.query(AppSetting.user_id).filter(
            AppSetting.key == "openai_api_key",
            AppSetting.user_id.isnot(None),
            AppSetting.value.isnot(None),
            AppSetting.value != "",
        ).all()
    }
    return [
        _UserWithCount(
            **UserOut.model_validate(u).model_dump(),
            nick_count=int(nick_counts.get(u.id, 0)),
            clone_count=int(clone_counts.get(u.id, 0)),
            live_reply_enabled_count=int(reply_on_counts.get(u.id, 0)),
            openai_own_key_set=u.id in own_key_user_ids,
        )
        for u in users
    ]


@router.get("/users/{user_id}/nicks", response_model=list[_NickDetail])
def list_user_nicks(
    user_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not db.get(User, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    rows = (
        db.query(NickLive, NickLiveSetting)
        .outerjoin(NickLiveSetting, NickLiveSetting.nick_live_id == NickLive.id)
        .filter(NickLive.user_id == user_id)
        .order_by(NickLive.id.asc())
        .all()
    )
    out: list[_NickDetail] = []
    for nick, setting in rows:
        mode = setting.reply_mode if setting else "none"
        out.append(_NickDetail(
            id=nick.id,
            name=nick.name,
            shopee_user_id=nick.shopee_user_id,
            reply_mode=mode,
            reply_enabled=mode != "none",
            reply_to_host=bool(setting.reply_to_host) if setting else False,
            reply_to_moderator=bool(setting.reply_to_moderator) if setting else False,
            auto_post_enabled=bool(setting.auto_post_enabled) if setting else False,
            auto_pin_enabled=bool(setting.auto_pin_enabled) if setting else False,
        ))
    return out


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
        ai_key_mode=body.ai_key_mode,
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
    if body.ai_key_mode is not None and body.ai_key_mode != u.ai_key_mode:
        u.ai_key_mode = body.ai_key_mode
        changed = True
        from app.models.nick_live import NickLive as _NL
        nick_ids = [nid for (nid,) in db.query(_NL.id)
                    .filter(_NL.user_id == u.id).all()]
        for nid in nick_ids:
            nick_cache.invalidate_settings(nid)
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
    from app.services.settings_service import invalidate_relive_key_cache
    nick_cache._settings.clear()
    invalidate_relive_key_cache()


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
