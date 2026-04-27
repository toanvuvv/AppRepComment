"""/api/seeding/proxies — proxy CRUD, bulk import, round-robin assignment."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.seeding import SeedingClone, SeedingProxy
from app.models.user import User
from app.schemas.seeding_proxy import (
    ProxyAssignRequest,
    ProxyAssignResult,
    ProxyCreate,
    ProxyImportRequest,
    ProxyImportResult,
    ProxyOut,
    ProxyUpdate,
    RequireProxySetting,
)
from app.services.seeding_proxy_service import (
    REQUIRE_PROXY_SETTING_KEY,
    assign_round_robin,
    clear_clone_cache_for_proxy,
    import_bulk,
    refresh_clone_cache_for_proxy,
)
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/seeding/proxies", tags=["seeding-proxy"])


def _owned_proxy(db: Session, proxy_id: int, user_id: int) -> SeedingProxy:
    row = db.query(SeedingProxy).filter(
        SeedingProxy.id == proxy_id, SeedingProxy.user_id == user_id
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Proxy not found")
    return row


def _to_out(db: Session, p: SeedingProxy) -> ProxyOut:
    used_by = db.query(SeedingClone).filter(
        SeedingClone.proxy_id == p.id
    ).count()
    return ProxyOut(
        id=p.id, scheme=p.scheme, host=p.host, port=p.port,
        username=p.username, note=p.note, created_at=p.created_at,
        used_by_count=used_by,
    )


@router.get("", response_model=list[ProxyOut])
def list_proxies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProxyOut]:
    rows = (
        db.query(SeedingProxy)
        .filter(SeedingProxy.user_id == current_user.id)
        .order_by(SeedingProxy.id.asc())
        .all()
    )
    return [_to_out(db, p) for p in rows]


@router.post("", response_model=ProxyOut)
def create_proxy(
    payload: ProxyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProxyOut:
    row = SeedingProxy(
        user_id=current_user.id,
        scheme=payload.scheme, host=payload.host, port=payload.port,
        username=payload.username, password=payload.password,
        note=payload.note,
    )
    db.add(row)
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001 — UNIQUE violation
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Proxy already exists",
        ) from exc
    db.refresh(row)
    return _to_out(db, row)


@router.patch("/{proxy_id}", response_model=ProxyOut)
def update_proxy(
    proxy_id: int,
    payload: ProxyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProxyOut:
    row = _owned_proxy(db, proxy_id, current_user.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    refresh_clone_cache_for_proxy(row.id)
    return _to_out(db, row)


@router.delete("/{proxy_id}", status_code=204)
def delete_proxy(
    proxy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    row = _owned_proxy(db, proxy_id, current_user.id)
    clear_clone_cache_for_proxy(row.id)
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.post("/import", response_model=ProxyImportResult)
def import_proxies(
    payload: ProxyImportRequest,
    current_user: User = Depends(get_current_user),
) -> ProxyImportResult:
    return import_bulk(current_user.id, payload.scheme, payload.raw_text)


@router.post("/assign", response_model=ProxyAssignResult)
def assign_proxies(
    payload: ProxyAssignRequest,
    current_user: User = Depends(get_current_user),
) -> ProxyAssignResult:
    return assign_round_robin(current_user.id, payload.only_unassigned)


@router.get("/setting", response_model=RequireProxySetting)
def get_proxy_setting(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RequireProxySetting:
    svc = SettingsService(db, user_id=current_user.id)
    raw = svc.get_setting(REQUIRE_PROXY_SETTING_KEY)
    return RequireProxySetting(require_proxy=(raw == "true"))


@router.put("/setting", response_model=RequireProxySetting)
def set_proxy_setting(
    payload: RequireProxySetting,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RequireProxySetting:
    svc = SettingsService(db, user_id=current_user.id)
    svc.set_setting(
        REQUIRE_PROXY_SETTING_KEY,
        "true" if payload.require_proxy else "false",
    )
    return payload
