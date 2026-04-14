# backend/app/routers/settings.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_api_key
from app.schemas.settings import (
    AutoPostTemplateCreate,
    AutoPostTemplateResponse,
    AutoPostTemplateUpdate,
    BannedWordsResponse,
    BannedWordsUpdate,
    KnowledgeAIConfigResponse,
    KnowledgeAIConfigUpdate,
    OpenAIConfigResponse,
    OpenAIConfigUpdate,
    ReplyTemplateCreate,
    ReplyTemplateResponse,
    SystemPromptResponse,
    SystemPromptUpdate,
)
from app.services.ai_reply_service import generate_reply
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


# --- Test AI ---

@router.post("/test-ai")
async def test_ai(db: Session = Depends(get_db)) -> dict:
    """Test OpenAI connection with current config."""
    svc = SettingsService(db)
    api_key = svc.get_openai_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="OpenAI API Key chưa được cấu hình")
    model = svc.get_setting("openai_model") or "gpt-4o"
    system_prompt = svc.get_system_prompt() or "Bạn là nhân viên CSKH."
    reply = await generate_reply(
        api_key=api_key,
        model=model,
        system_prompt=system_prompt,
        comment_text="Sản phẩm này có ship COD không ạ?",
        guest_name="Khách test",
    )
    if reply is None:
        raise HTTPException(status_code=502, detail="OpenAI không phản hồi. Kiểm tra lại API key và model.")
    return {"reply": reply, "model": model}


# --- Knowledge AI config ---


@router.get("/knowledge-ai", response_model=KnowledgeAIConfigResponse)
def get_knowledge_ai_config(db: Session = Depends(get_db)):
    svc = SettingsService(db)
    return KnowledgeAIConfigResponse(
        system_prompt=svc.get_knowledge_system_prompt(),
        model=svc.get_knowledge_model() or "gpt-4o",
    )


@router.put("/knowledge-ai")
def update_knowledge_ai_config(
    payload: KnowledgeAIConfigUpdate, db: Session = Depends(get_db)
):
    svc = SettingsService(db)
    if payload.system_prompt is not None:
        svc.set_setting("knowledge_system_prompt", payload.system_prompt)
    if payload.model is not None:
        svc.set_setting("knowledge_model", payload.model)
    return {"status": "saved"}


# --- Banned words ---


@router.get("/banned-words", response_model=BannedWordsResponse)
def get_banned_words(db: Session = Depends(get_db)):
    svc = SettingsService(db)
    return BannedWordsResponse(words=svc.get_banned_words())


@router.put("/banned-words")
def update_banned_words(payload: BannedWordsUpdate, db: Session = Depends(get_db)):
    svc = SettingsService(db)
    svc.set_banned_words(payload.words)
    return {"status": "saved"}
