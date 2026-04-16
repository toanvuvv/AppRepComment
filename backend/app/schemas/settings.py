# backend/app/schemas/settings.py
from pydantic import BaseModel, Field


class OpenAIConfigUpdate(BaseModel):
    api_key: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=100)


class OpenAIConfigResponse(BaseModel):
    api_key_set: bool
    model: str | None


class SystemPromptUpdate(BaseModel):
    prompt: str = Field(max_length=10000)


class SystemPromptResponse(BaseModel):
    prompt: str


class ReplyTemplateCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class ReplyTemplateResponse(BaseModel):
    id: int
    content: str
    model_config = {"from_attributes": True}


class AutoPostTemplateCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    min_interval_seconds: int = Field(ge=10, le=86400, default=60)
    max_interval_seconds: int = Field(ge=10, le=86400, default=300)


class AutoPostTemplateUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    min_interval_seconds: int | None = Field(default=None, ge=10, le=86400)
    max_interval_seconds: int | None = Field(default=None, ge=10, le=86400)


class AutoPostTemplateResponse(BaseModel):
    id: int
    content: str
    min_interval_seconds: int
    max_interval_seconds: int
    model_config = {"from_attributes": True}


class NickLiveSettingsUpdate(BaseModel):
    ai_reply_enabled: bool | None = None
    auto_reply_enabled: bool | None = None
    auto_post_enabled: bool | None = None
    knowledge_reply_enabled: bool | None = None
    host_reply_enabled: bool | None = None
    host_auto_post_enabled: bool | None = None
    host_proxy: str | None = None


class NickLiveSettingsResponse(BaseModel):
    nick_live_id: int
    ai_reply_enabled: bool
    auto_reply_enabled: bool
    auto_post_enabled: bool
    knowledge_reply_enabled: bool
    host_reply_enabled: bool
    host_auto_post_enabled: bool
    model_config = {"from_attributes": True}


# --- Knowledge Products ---


class KnowledgeProductImportRequest(BaseModel):
    raw_json: str = Field(min_length=10)


class KnowledgeProductResponse(BaseModel):
    pk: int
    product_order: int
    nick_live_id: int
    item_id: int
    shop_id: int
    name: str
    keywords: str
    price_min: int | None
    price_max: int | None
    discount_pct: int | None
    in_stock: bool
    stock_qty: int | None
    sold: int | None
    rating: float | None
    rating_count: int | None
    voucher_info: str | None
    promotion_info: str | None
    model_config = {"from_attributes": True}


# --- Knowledge AI Config ---


class KnowledgeAIConfigUpdate(BaseModel):
    system_prompt: str | None = Field(default=None, max_length=10000)
    model: str | None = Field(default=None, min_length=1, max_length=100)


class KnowledgeAIConfigResponse(BaseModel):
    system_prompt: str
    model: str


# --- Banned Words ---


class BannedWordsUpdate(BaseModel):
    words: list[str]


class BannedWordsResponse(BaseModel):
    words: list[str]
