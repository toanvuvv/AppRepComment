# backend/app/schemas/settings.py
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ReplyMode = Literal["none", "knowledge", "ai", "template"]


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
    reply_mode: ReplyMode | None = None
    reply_to_host: bool | None = None
    reply_to_moderator: bool | None = None
    auto_post_enabled: bool | None = None
    auto_post_to_host: bool | None = None
    auto_post_to_moderator: bool | None = None
    host_proxy: str | None = None

    # Auto-pin fields
    auto_pin_enabled: bool | None = None
    pin_min_interval_minutes: int | None = Field(default=None, ge=1, le=60)
    pin_max_interval_minutes: int | None = Field(default=None, ge=1, le=60)

    @model_validator(mode="after")
    def _check_pin_interval(self):
        lo, hi = self.pin_min_interval_minutes, self.pin_max_interval_minutes
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("pin_min_interval_minutes phải <= pin_max_interval_minutes")
        return self


class NickLiveSettingsResponse(BaseModel):
    nick_live_id: int
    reply_mode: ReplyMode
    reply_to_host: bool
    reply_to_moderator: bool
    auto_post_enabled: bool
    auto_post_to_host: bool
    auto_post_to_moderator: bool
    auto_pin_enabled: bool
    pin_min_interval_minutes: int
    pin_max_interval_minutes: int
    model_config = {"from_attributes": True}


# --- Knowledge Products ---


class KnowledgeProductImportRequest(BaseModel):
    raw_json: str = Field(min_length=10)


class KnowledgeProductParseRequest(BaseModel):
    session_id: int = Field(gt=0)


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


class AutoPinStartRequest(BaseModel):
    session_id: int = Field(gt=0)


# --- System Keys (admin-only) ---


class SystemKeysResponse(BaseModel):
    relive_api_key_set: bool
    openai_api_key_set: bool
    openai_model: str | None


class SystemReliveUpdate(BaseModel):
    api_key: str = Field(min_length=1, max_length=500)


class SystemOpenAIUpdate(BaseModel):
    api_key: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=100)
