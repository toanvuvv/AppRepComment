# backend/app/routers/settings.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_api_key
from app.schemas.settings import (
    AutoPostTemplateCreate,
    AutoPostTemplateResponse,
    AutoPostTemplateUpdate,
    OpenAIConfigResponse,
    OpenAIConfigUpdate,
    ReplyTemplateCreate,
    ReplyTemplateResponse,
    SystemPromptResponse,
    SystemPromptUpdate,
)
from app.services.settings_service import SettingsService

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(require_api_key)],
)


# --- OpenAI config ---

@router.get("/openai", response_model=OpenAIConfigResponse)
def get_openai_config(db: Session = Depends(get_db)) -> OpenAIConfigResponse:
    svc = SettingsService(db)
    config = svc.get_openai_config()
    return OpenAIConfigResponse(**config)


@router.put("/openai")
def update_openai_config(
    payload: OpenAIConfigUpdate, db: Session = Depends(get_db)
) -> dict:
    svc = SettingsService(db)
    svc.set_setting("openai_api_key", payload.api_key)
    svc.set_setting("openai_model", payload.model)
    return {"status": "saved"}


# --- System prompt ---

@router.get("/system-prompt", response_model=SystemPromptResponse)
def get_system_prompt(db: Session = Depends(get_db)) -> SystemPromptResponse:
    svc = SettingsService(db)
    return SystemPromptResponse(prompt=svc.get_system_prompt())


@router.put("/system-prompt")
def update_system_prompt(
    payload: SystemPromptUpdate, db: Session = Depends(get_db)
) -> dict:
    svc = SettingsService(db)
    svc.set_setting("ai_system_prompt", payload.prompt)
    return {"status": "saved"}


# --- Reply templates ---

@router.get("/reply-templates", response_model=list[ReplyTemplateResponse])
def list_reply_templates(db: Session = Depends(get_db)) -> list:
    return SettingsService(db).get_reply_templates()


@router.post("/reply-templates", response_model=ReplyTemplateResponse)
def create_reply_template(
    payload: ReplyTemplateCreate, db: Session = Depends(get_db)
):
    return SettingsService(db).create_reply_template(payload.content)


@router.delete("/reply-templates/{template_id}")
def delete_reply_template(template_id: int, db: Session = Depends(get_db)) -> dict:
    if not SettingsService(db).delete_reply_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"detail": "Deleted"}


# --- Auto-post templates ---

@router.get("/auto-post-templates", response_model=list[AutoPostTemplateResponse])
def list_auto_post_templates(db: Session = Depends(get_db)) -> list:
    return SettingsService(db).get_auto_post_templates()


@router.post("/auto-post-templates", response_model=AutoPostTemplateResponse)
def create_auto_post_template(
    payload: AutoPostTemplateCreate, db: Session = Depends(get_db)
):
    return SettingsService(db).create_auto_post_template(
        payload.content, payload.min_interval_seconds, payload.max_interval_seconds
    )


@router.put("/auto-post-templates/{template_id}", response_model=AutoPostTemplateResponse)
def update_auto_post_template(
    template_id: int, payload: AutoPostTemplateUpdate, db: Session = Depends(get_db)
):
    result = SettingsService(db).update_auto_post_template(
        template_id,
        content=payload.content,
        min_interval=payload.min_interval_seconds,
        max_interval=payload.max_interval_seconds,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Template not found")
    return result


@router.delete("/auto-post-templates/{template_id}")
def delete_auto_post_template(template_id: int, db: Session = Depends(get_db)) -> dict:
    if not SettingsService(db).delete_auto_post_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"detail": "Deleted"}
