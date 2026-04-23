# backend/app/routers/settings.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
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
from app.services.nick_cache import nick_cache
from app.services.settings_service import SettingsService


def _invalidate_all_nick_settings() -> None:
    """Drop every cached per-nick settings snapshot.

    App-level settings (api key, model, system prompt, knowledge config,
    banned words) flow into every nick's snapshot, so a change here must
    force a refresh on the next reply cycle for all nicks. We deliberately
    clear the private dict on the cache singleton rather than exposing a
    new public method, per Wave 2 instructions.
    """
    # Direct dict clear — the cache API doesn't publish a bulk-invalidate
    # helper, but the underlying storage is a plain dict.
    nick_cache._settings.clear()

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
)


# --- OpenAI config ---

@router.get("/openai", response_model=OpenAIConfigResponse)
def get_openai_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OpenAIConfigResponse:
    svc = SettingsService(db, user_id=current_user.id)
    config = svc.get_openai_config()
    return OpenAIConfigResponse(
        **config,
        ai_key_mode=current_user.ai_key_mode,
        is_managed_by_admin=current_user.ai_key_mode == "system",
    )


@router.put("/openai")
def update_openai_config(
    payload: OpenAIConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    svc = SettingsService(db, user_id=current_user.id)
    svc.set_setting("openai_api_key", payload.api_key)
    svc.set_setting("openai_model", payload.model)
    _invalidate_all_nick_settings()
    return {"status": "saved"}


# --- System prompt ---

@router.get("/system-prompt", response_model=SystemPromptResponse)
def get_system_prompt(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SystemPromptResponse:
    svc = SettingsService(db, user_id=current_user.id)
    return SystemPromptResponse(prompt=svc.get_system_prompt())


@router.put("/system-prompt")
def update_system_prompt(
    payload: SystemPromptUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    svc = SettingsService(db, user_id=current_user.id)
    svc.set_setting("ai_system_prompt", payload.prompt)
    _invalidate_all_nick_settings()
    return {"status": "saved"}


# --- Reply templates ---

@router.get("/reply-templates", response_model=list[ReplyTemplateResponse])
def list_reply_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list:
    return SettingsService(db, user_id=current_user.id).get_reply_templates()


@router.post("/reply-templates", response_model=ReplyTemplateResponse)
def create_reply_template(
    payload: ReplyTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return SettingsService(db, user_id=current_user.id).create_reply_template(payload.content)


@router.delete("/reply-templates/{template_id}")
def delete_reply_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not SettingsService(db, user_id=current_user.id).delete_reply_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"detail": "Deleted"}


# --- Auto-post templates ---

@router.get("/auto-post-templates", response_model=list[AutoPostTemplateResponse])
def list_auto_post_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list:
    return SettingsService(db, user_id=current_user.id).get_auto_post_templates()


@router.post("/auto-post-templates", response_model=AutoPostTemplateResponse)
def create_auto_post_template(
    payload: AutoPostTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return SettingsService(db, user_id=current_user.id).create_auto_post_template(
        payload.content, payload.min_interval_seconds, payload.max_interval_seconds
    )


@router.put("/auto-post-templates/{template_id}", response_model=AutoPostTemplateResponse)
def update_auto_post_template(
    template_id: int,
    payload: AutoPostTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = SettingsService(db, user_id=current_user.id).update_auto_post_template(
        template_id,
        content=payload.content,
        min_interval=payload.min_interval_seconds,
        max_interval=payload.max_interval_seconds,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Template not found")
    return result


@router.delete("/auto-post-templates/{template_id}")
def delete_auto_post_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not SettingsService(db, user_id=current_user.id).delete_auto_post_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"detail": "Deleted"}


# --- Test AI ---

@router.post("/test-ai")
async def test_ai(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Test OpenAI connection with current config."""
    svc = SettingsService(db, user_id=current_user.id)
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
def get_knowledge_ai_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = SettingsService(db, user_id=current_user.id)
    return KnowledgeAIConfigResponse(
        system_prompt=svc.get_knowledge_system_prompt(),
        model=svc.get_knowledge_model() or "gpt-4o",
    )


@router.put("/knowledge-ai")
def update_knowledge_ai_config(
    payload: KnowledgeAIConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = SettingsService(db, user_id=current_user.id)
    if payload.system_prompt is not None:
        svc.set_setting("knowledge_system_prompt", payload.system_prompt)
    if payload.model is not None:
        svc.set_setting("knowledge_model", payload.model)
    _invalidate_all_nick_settings()
    return {"status": "saved"}


# --- Banned words ---


@router.get("/banned-words", response_model=BannedWordsResponse)
def get_banned_words(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = SettingsService(db, user_id=current_user.id)
    return BannedWordsResponse(words=svc.get_banned_words())


@router.put("/banned-words")
def update_banned_words(
    payload: BannedWordsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = SettingsService(db, user_id=current_user.id)
    svc.set_banned_words(payload.words)
    _invalidate_all_nick_settings()
    return {"status": "saved"}


# --- Relive API key ---


@router.get("/relive-api-key")
def get_relive_key(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = SettingsService(db, user_id=current_user.id)
    key = svc.get_setting("relive_api_key")
    # Never return the key value in plaintext; only signal whether it is set.
    return {"api_key_set": bool(key)}


@router.put("/relive-api-key")
def update_relive_key(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = SettingsService(db, user_id=current_user.id)
    svc.set_setting("relive_api_key", payload.get("api_key", ""))
    return {"status": "saved"}
