# backend/app/routers/knowledge.py
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.nick_live import NickLive
from app.models.user import User
from app.schemas.settings import (
    KnowledgeProductImportRequest,
    KnowledgeProductParseRequest,
    KnowledgeProductResponse,
)
from app.services.knowledge_product_service import KnowledgeProductService
from app.services.nick_cache import nick_cache
from app.services.relive_service import fetch_livestream_items
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/nick-lives/{nick_live_id}/knowledge",
    tags=["knowledge"],
)


def _require_nick_ownership(nick_live_id: int, current_user: User, db: Session) -> NickLive:
    nick = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == current_user.id
    ).first()
    if not nick:
        raise HTTPException(status_code=404, detail="Nick not found")
    return nick


@router.post("/import", response_model=list[KnowledgeProductResponse])
def import_products(
    nick_live_id: int,
    payload: KnowledgeProductImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Parse Shopee cart JSON, extract keywords (code-based), save products."""
    _require_nick_ownership(nick_live_id, current_user, db)
    kp_svc = KnowledgeProductService(db)
    try:
        products = kp_svc.import_products(
            nick_live_id=nick_live_id,
            raw_json=payload.raw_json,
        )
        nick_cache.invalidate_products(nick_live_id)
        return products
    except Exception as e:
        logger.error(f"Import failed for nick_live={nick_live_id}: {e}")
        raise HTTPException(status_code=400, detail=f"Import failed: {e}")


@router.post("/parse", response_model=list[KnowledgeProductResponse])
async def parse_products_from_relive(
    nick_live_id: int,
    payload: KnowledgeProductParseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch live items from relive.vn API and import as knowledge products."""
    nick = _require_nick_ownership(nick_live_id, current_user, db)

    svc = SettingsService(db)
    api_key = svc.get_setting("relive_api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="Relive API key not configured")

    nick_settings = svc.get_or_create_nick_settings(nick_live_id)
    proxy = getattr(nick_settings, "host_proxy", None)

    try:
        raw_json = await fetch_livestream_items(
            api_key=api_key,
            cookies=nick.cookies,
            session_id=payload.session_id,
            proxy=proxy,
        )
    except ValueError as exc:
        logger.error("parse_products fetch failed nick=%s: %s", nick_live_id, exc)
        raise HTTPException(status_code=502, detail=str(exc))

    kp_svc = KnowledgeProductService(db)
    try:
        products = kp_svc.import_products(
            nick_live_id=nick_live_id,
            raw_json=raw_json,
        )
        nick_cache.invalidate_products(nick_live_id)
        return products
    except Exception as e:
        logger.error(f"Parse import failed for nick_live={nick_live_id}: {e}")
        raise HTTPException(status_code=400, detail=f"Parse failed: {e}")


@router.get("/products", response_model=list[KnowledgeProductResponse])
def list_products(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all knowledge products for this nick_live."""
    _require_nick_ownership(nick_live_id, current_user, db)
    kp_svc = KnowledgeProductService(db)
    return kp_svc.get_products(nick_live_id)


@router.delete("/products")
def delete_all_products(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete all knowledge products for this nick_live."""
    _require_nick_ownership(nick_live_id, current_user, db)
    kp_svc = KnowledgeProductService(db)
    count = kp_svc.delete_products(nick_live_id)
    nick_cache.invalidate_products(nick_live_id)
    return {"deleted": count}
