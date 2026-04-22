"""/api/seeding/* — clones, templates, manual send, auto run, logs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.nick_live import NickLive
from app.models.seeding import (
    SeedingClone,
    SeedingCommentTemplate,
    SeedingLog,
    SeedingLogSession,
)
from app.models.user import User
from app.schemas.seeding import (
    CloneRateLimitedError,
    HostConfigMissingError,
    SeedingAutoStartRequest,
    SeedingAutoStartResponse,
    SeedingAutoStopRequest,
    SeedingCloneCreate,
    SeedingCloneResponse,
    SeedingCloneUpdate,
    SeedingLogResponse,
    SeedingLogSessionResponse,
    SeedingManualSendRequest,
    SeedingManualSendResponse,
    SeedingRunStatus,
    SeedingTemplateBulkRequest,
    SeedingTemplateCreate,
    SeedingTemplateResponse,
    SeedingTemplateUpdate,
)
from app.services.seeding_scheduler import SeedingRunConfig, seeding_scheduler
from app.services.seeding_sender import seeding_sender

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/seeding", tags=["seeding"])


# ---------- Helpers ----------

def _owned_clone(db: Session, clone_id: int, user_id: int) -> SeedingClone:
    row = db.query(SeedingClone).filter(
        SeedingClone.id == clone_id, SeedingClone.user_id == user_id
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Clone not found")
    return row


def _owned_template(db: Session, tpl_id: int, user_id: int) -> SeedingCommentTemplate:
    row = db.query(SeedingCommentTemplate).filter(
        SeedingCommentTemplate.id == tpl_id,
        SeedingCommentTemplate.user_id == user_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return row


def _owned_nick(db: Session, nick_live_id: int, user_id: int) -> NickLive:
    row = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == user_id
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Nick not found")
    return row


# ---------- Clone CRUD ----------

@router.post("/clones", response_model=SeedingCloneResponse)
def create_clone(
    payload: SeedingCloneCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SeedingClone:
    if current_user.max_clones is not None:
        n = db.query(SeedingClone).filter(
            SeedingClone.user_id == current_user.id
        ).count()
        if n >= current_user.max_clones:
            raise HTTPException(
                status_code=403,
                detail=f"Clone quota exceeded (max {current_user.max_clones})",
            )

    row = SeedingClone(
        user_id=current_user.id,
        name=payload.name,
        shopee_user_id=payload.shopee_user_id,
        avatar=payload.avatar,
        cookies=payload.cookies,
        proxy=payload.proxy,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/clones", response_model=list[SeedingCloneResponse])
def list_clones(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SeedingClone]:
    return (
        db.query(SeedingClone)
        .filter(SeedingClone.user_id == current_user.id)
        .order_by(SeedingClone.created_at.desc())
        .all()
    )


@router.patch("/clones/{clone_id}", response_model=SeedingCloneResponse)
def update_clone(
    clone_id: int,
    payload: SeedingCloneUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SeedingClone:
    row = _owned_clone(db, clone_id, current_user.id)
    if payload.name is not None:
        row.name = payload.name
    if payload.cookies is not None:
        row.cookies = payload.cookies
    if payload.proxy is not None:
        row.proxy = payload.proxy
    db.commit()
    db.refresh(row)
    return row


@router.delete("/clones/{clone_id}", status_code=204)
def delete_clone(
    clone_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    row = _owned_clone(db, clone_id, current_user.id)

    for cfg in seeding_scheduler.running_configs(current_user.id):
        if clone_id in cfg.clone_ids:
            raise HTTPException(
                status_code=409,
                detail="Clone đang nằm trong auto-run, stop trước rồi xoá",
            )

    db.delete(row)
    db.commit()
    return Response(status_code=204)


# ---------- Template CRUD ----------

@router.post("/templates", response_model=SeedingTemplateResponse)
def create_template(
    payload: SeedingTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SeedingCommentTemplate:
    row = SeedingCommentTemplate(
        user_id=current_user.id,
        content=payload.content,
        enabled=payload.enabled,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


@router.get("/templates", response_model=list[SeedingTemplateResponse])
def list_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SeedingCommentTemplate]:
    return (db.query(SeedingCommentTemplate)
            .filter(SeedingCommentTemplate.user_id == current_user.id)
            .order_by(SeedingCommentTemplate.created_at.desc())
            .all())


@router.patch("/templates/{tpl_id}", response_model=SeedingTemplateResponse)
def update_template(
    tpl_id: int,
    payload: SeedingTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SeedingCommentTemplate:
    row = _owned_template(db, tpl_id, current_user.id)
    if payload.content is not None:
        row.content = payload.content
    if payload.enabled is not None:
        row.enabled = payload.enabled
    db.commit(); db.refresh(row)
    return row


@router.delete("/templates/{tpl_id}", status_code=204)
def delete_template(
    tpl_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    row = _owned_template(db, tpl_id, current_user.id)
    db.delete(row); db.commit()
    return Response(status_code=204)


@router.post("/templates/bulk", response_model=list[SeedingTemplateResponse])
def bulk_create_templates(
    payload: SeedingTemplateBulkRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SeedingCommentTemplate]:
    created: list[SeedingCommentTemplate] = []
    for line in payload.lines:
        content = line.strip()
        if not content:
            continue
        row = SeedingCommentTemplate(
            user_id=current_user.id, content=content, enabled=True,
        )
        db.add(row); created.append(row)
    db.commit()
    for r in created:
        db.refresh(r)
    return created


# ---------- Manual send ----------

def _find_or_create_manual_session(
    db: Session, *, user_id: int, nick_live_id: int, shopee_session_id: int,
) -> SeedingLogSession:
    today_utc = datetime.now(timezone.utc).date()
    row = (
        db.query(SeedingLogSession)
        .filter(
            SeedingLogSession.user_id == user_id,
            SeedingLogSession.nick_live_id == nick_live_id,
            SeedingLogSession.shopee_session_id == shopee_session_id,
            SeedingLogSession.mode == "manual",
        )
        .order_by(SeedingLogSession.started_at.desc())
        .first()
    )
    if row is not None and row.started_at.date() == today_utc:
        return row
    row = SeedingLogSession(
        user_id=user_id,
        nick_live_id=nick_live_id,
        shopee_session_id=shopee_session_id,
        mode="manual",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/manual/send", response_model=SeedingManualSendResponse)
async def manual_send(
    payload: SeedingManualSendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SeedingManualSendResponse:
    _owned_clone(db, payload.clone_id, current_user.id)
    _owned_nick(db, payload.nick_live_id, current_user.id)

    log_session = _find_or_create_manual_session(
        db,
        user_id=current_user.id,
        nick_live_id=payload.nick_live_id,
        shopee_session_id=payload.shopee_session_id,
    )

    try:
        log = await seeding_sender.send(
            clone_id=payload.clone_id,
            nick_live_id=payload.nick_live_id,
            shopee_session_id=payload.shopee_session_id,
            content=payload.content,
            template_id=None,
            mode="manual",
            log_session_id=log_session.id,
        )
    except CloneRateLimitedError as e:
        raise HTTPException(
            status_code=429,
            detail={
                "retry_after_sec": e.retry_after_sec,
                "message": f"Clone vừa gửi, chờ {e.retry_after_sec}s",
            },
        )
    except HostConfigMissingError:
        raise HTTPException(
            status_code=400,
            detail="Nick host chưa setup host_config. Vào LiveScan → Host → Get Credentials",
        )
    except RuntimeError as e:
        return SeedingManualSendResponse(log_id=0, status="failed", error=str(e))

    return SeedingManualSendResponse(log_id=log.id, status="success", error=None)
