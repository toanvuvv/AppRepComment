# backend/app/routers/knowledge.py
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_api_key
from app.schemas.settings import (
    KnowledgeProductImportRequest,
    KnowledgeProductResponse,
)
from app.services.knowledge_product_service import KnowledgeProductService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/nick-lives/{nick_live_id}/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/import", response_model=list[KnowledgeProductResponse])
def import_products(
    nick_live_id: int,
    payload: KnowledgeProductImportRequest,
    db: Session = Depends(get_db),
):
    """Parse Shopee cart JSON, extract keywords (code-based), save products."""
    kp_svc = KnowledgeProductService(db)
    try:
        products = kp_svc.import_products(
            nick_live_id=nick_live_id,
            raw_json=payload.raw_json,
        )
        return products
    except Exception as e:
        logger.error(f"Import failed for nick_live={nick_live_id}: {e}")
        raise HTTPException(status_code=400, detail=f"Import failed: {e}")


@router.get("/products", response_model=list[KnowledgeProductResponse])
def list_products(
    nick_live_id: int,
    db: Session = Depends(get_db),
):
    """List all knowledge products for this nick_live."""
    kp_svc = KnowledgeProductService(db)
    return kp_svc.get_products(nick_live_id)


@router.delete("/products")
def delete_all_products(
    nick_live_id: int,
    db: Session = Depends(get_db),
):
    """Delete all knowledge products for this nick_live."""
    kp_svc = KnowledgeProductService(db)
    count = kp_svc.delete_products(nick_live_id)
    return {"deleted": count}
