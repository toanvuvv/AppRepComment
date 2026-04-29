# backend/app/routers/settings.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, resolve_user_context
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
    # Direct dict clear â€” the cache API doesn't publish a bulk-invalidate
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
    ctx_user: User = Depends(resolve_user_context),
) -> OpenAIConfigResponse:
    svc = SettingsService(db, user_id=ctx_user.id)
    config = svc.get_openai_config()
    return OpenAIConfigResponse(
        **config,
        ai_key_mode=ctx_user.ai_key_mode,
        is_managed_by_admin=ctx_user.ai_key_mode == "system",
    )


@router.put("/openai")
def update_openai_config(
    payload: OpenAIConfigUpdate,
    db: Session = Depends(get_db),
    ctx_user: User = Depends(resolve_user_context),
) -> dict:
    if ctx_user.ai_key_mode == "system":
        raise HTTPException(
            status_code=403,
            detail="TÃ i khoáº£n Ä‘ang dÃ¹ng system key; khÃ´ng thá»ƒ tá»± cáº¥u hÃ¬nh",
        )
    svc = SettingsService(db, user_id=ctx_user.id)
    svc.set_setting("openai_api_key", payload.api_key)
    svc.set_setting("openai_model", payload.model)
    _invalidate_all_nick_settings()
    return {"status": "saved"}


# --- System prompt ---

@router.get("/system-prompt", response_model=SystemPromptResponse)
def get_system_prompt(
    db: Session = Depends(get_db),
    ctx_user: User = Depends(resolve_user_context),
) -> SystemPromptResponse:
    svc = SettingsService(db, user_id=ctx_user.id)
    return SystemPromptResponse(prompt=svc.get_system_prompt())


@router.put("/system-prompt")
def update_system_prompt(
    payload: SystemPromptUpdate,
    db: Session = Depends(get_db),
    ctx_user: User = Depends(resolve_user_context),
) -> dict:
    svc = SettingsService(db, user_id=ctx_user.id)
    svc.set_setting("ai_system_prompt", payload.prompt)
    _invalidate_all_nick_settings()
    return {"status": "saved"}


# --- Reply templates ---

@router.get("/reply-templates", response_model=list[ReplyTemplateResponse])
def list_reply_templates(
    db: Session = Depends(get_db),
    ctx_user: User = Depends(resolve_user_context),
) -> list:
    return SettingsService(db, user_id=ctx_user.id).get_reply_templates()


@router.post("/reply-templates", response_model=ReplyTemplateResponse)
def create_reply_template(
    payload: ReplyTemplateCreate,
    db: Session = Depends(get_db),
    ctx_user: User = Depends(resolve_user_context),
):
    return SettingsService(db, user_id=ctx_user.id).create_reply_template(payload.content)


@router.delete("/reply-templates/{template_id}")
def delete_reply_template(
    template_id: int,
    db: Session = Depends(get_db),
    ctx_user: User = Depends(resolve_user_context),
) -> dict:
    if not SettingsService(db, user_id=ctx_user.id).delete_reply_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"detail": "Deleted"}


# --- Auto-post templates ---

@router.get("/auto-post-templates", response_model=list[AutoPostTemplateResponse])
def list_auto_post_templates(
    db: Session = Depends(get_db),
    ctx_user: User = Depends(resolve_user_context),
) -> list:
    return SettingsService(db, user_id=ctx_user.id).get_auto_post_templates()


@router.post("/auto-post-templates", response_model=AutoPostTemplateResponse)
def create_auto_post_template(
    payload: AutoPostTemplateCreate,
    db: Session = Depends(get_db),
    ctx_user: User = Depends(resolve_user_context),
):
    return SettingsService(db, user_id=ctx_user.id).create_auto_post_template(
        payload.content, payload.min_interval_seconds, payload.max_interval_seconds
    )


@router.put("/auto-post-templates/{template_id}", response_model=AutoPostTemplateResponse)
def update_auto_post_template(
    template_id: int,
    payload: AutoPostTemplateUpdate,
    db: Session = Depends(get_db),
    ctx_user: User = Depends(resolve_user_context),
):
    result = SettingsService(db, user_id=ctx_user.id).update_auto_post_template(
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
    ctx_user: User = Depends(resolve_user_context),
) -> dict:
    if not SettingsService(db, user_id=ctx_user.id).delete_auto_post_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"detail": "Deleted"}


# --- Test AI ---

@router.post("/test-ai")
async def test_ai(
    db: Session = Depends(get_db),
    ctx_user: User = Depends(resolve_user_context),
) -> dict:
    """Test OpenAI connection with current config."""
    svc = SettingsService(db, user_id=ctx_user.id)
    api_key, model = svc.resolve_openai_config(ctx_user.ai_key_mode)
    if not api_key:
        if ctx_user.ai_key_mode == "system":
            raise HTTPException(status_code=400, detail="Admin chÆ°a cáº¥u hÃ¬nh System OpenAI key")
        raise HTTPException(status_code=400, detail="OpenAI API Key chÆ°a Ä‘Æ°á»£c cáº¥u hÃ¬nh")
    model = model or "gpt-4o"
    system_prompt = svc.get_system_prompt() or "Báº¡n lÃ  nhÃ¢n viÃªn CSKH."
    reply = await generate_reply(
        api_key=api_key,
        model=model,
        system_prompt=system_prompt,
        comment_text="Sáº£n pháº©m nÃ y cÃ³ ship COD khÃ´ng áº¡?",
        guest_name="KhÃ¡ch test",
    )
    if reply is None:
        raise HTTPException(status_code=502, detail="OpenAI khÃ´ng pháº£n há»“i. Kiá»ƒm tra láº¡i API key vÃ  model.")
    return {"reply": reply, "model": model}


# --- Knowledge AI config ---


@router.get("/knowledge-ai", response_model=KnowledgeAIConfigResponse)
def get_knowledge_ai_config(
    db: Session = Depends(get_db),
    ctx_user: User = Depends(resolve_user_context),
):
    svc = SettingsService(db, user_id=ctx_user.id)
    return KnowledgeAIConfigResponse(
        system_prompt=svc.get_knowledge_system_prompt(),
        model=svc.get_knowledge_model() or "gpt-4o",
    )


@router.put("/knowledge-ai")
def update_knowledge_ai_config(
    payload: KnowledgeAIConfigUpdate,
    db: Session = Depends(get_db),
    ctx_user: User = Depends(resolve_user_context),
):
    svc = SettingsService(db, user_id=ctx_user.id)
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
    ctx_user: User = Depends(resolve_user_context),
):
    svc = SettingsService(db, user_id=ctx_user.id)
    return BannedWordsResponse(words=svc.get_banned_words())


@router.put("/banned-words")
def update_banned_words(
    payload: BannedWordsUpdate,
    db: Session = Depends(get_db),
    ctx_user: User = Depends(resolve_user_context),
):
    svc = SettingsService(db, user_id=ctx_user.id)
    svc.set_banned_words(payload.words)
    _invalidate_all_nick_settings()
    return {"status": "saved"}


