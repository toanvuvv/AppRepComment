from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ---------- Clones ----------

class SeedingUserPayload(BaseModel):
    id: int
    name: str = Field(max_length=100)
    avatar: str | None = Field(default=None, max_length=500)


class SeedingCloneCreate(BaseModel):
    """Mirror of NickLiveCreate: nested {user: {...}, cookies} OR flat."""

    name: str | None = Field(default=None, max_length=100)
    shopee_user_id: int | None = None
    avatar: str | None = Field(default=None, max_length=500)
    user: SeedingUserPayload | None = None
    cookies: str = Field(min_length=1, max_length=20000)
    proxy: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _coerce_user(self) -> "SeedingCloneCreate":
        if self.user is not None:
            if self.name is not None or self.shopee_user_id is not None:
                raise ValueError(
                    "Provide either flat fields (name, shopee_user_id) or nested user — not both"
                )
            self.name = self.user.name
            self.shopee_user_id = self.user.id
            self.avatar = self.avatar or self.user.avatar
        if not self.name or self.shopee_user_id is None:
            raise ValueError("name and shopee_user_id required (supply either flat or nested form)")
        return self


class SeedingCloneUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    cookies: str | None = Field(default=None, min_length=1, max_length=20000)
    proxy: str | None = Field(default=None, max_length=255)


class SeedingCloneResponse(BaseModel):
    id: int
    name: str
    shopee_user_id: int
    avatar: str | None
    proxy: str | None
    last_sent_at: datetime | None
    consecutive_failures: int = 0
    last_status: str | None = None
    last_error: str | None = None
    auto_disabled: bool = False
    created_at: datetime
    model_config = {"from_attributes": True}


# ---------- Templates ----------

class SeedingTemplateCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    enabled: bool = True


class SeedingTemplateUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    enabled: bool | None = None


class SeedingTemplateResponse(BaseModel):
    id: int
    content: str
    enabled: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class SeedingTemplateBulkRequest(BaseModel):
    lines: list[str] = Field(min_length=1, max_length=1000)


# ---------- Manual send ----------

class SeedingManualSendRequest(BaseModel):
    clone_id: int
    nick_live_id: int
    shopee_session_id: int
    content: str = Field(min_length=1, max_length=2000)


class SeedingManualSendResponse(BaseModel):
    log_id: int
    status: Literal["success", "failed"]
    error: str | None = None


# ---------- Auto run ----------

class SeedingAutoStartRequest(BaseModel):
    nick_live_id: int
    shopee_session_id: int
    clone_ids: list[int] = Field(min_length=1)
    min_interval_sec: int = Field(ge=10)
    max_interval_sec: int = Field(ge=10)

    @model_validator(mode="after")
    def _min_le_max(self) -> "SeedingAutoStartRequest":
        if self.min_interval_sec > self.max_interval_sec:
            raise ValueError("min_interval_sec must be <= max_interval_sec")
        return self


class SeedingAutoStartResponse(BaseModel):
    log_session_id: int
    status: Literal["started"]


class SeedingAutoStopRequest(BaseModel):
    log_session_id: int


class SeedingRunStatus(BaseModel):
    log_session_id: int
    running: bool
    nick_live_id: int
    shopee_session_id: int
    clone_ids: list[int]
    min_interval_sec: int
    max_interval_sec: int
    started_at: datetime
    stopped_at: datetime | None
    model_config = {"from_attributes": True}


# ---------- Logs ----------

class SeedingLogSessionResponse(BaseModel):
    id: int
    user_id: int
    nick_live_id: int
    shopee_session_id: int
    mode: Literal["manual", "auto"]
    started_at: datetime
    stopped_at: datetime | None
    model_config = {"from_attributes": True}


class SeedingLogResponse(BaseModel):
    id: int
    seeding_log_session_id: int
    clone_id: int
    template_id: int | None
    content: str
    status: Literal["success", "failed", "rate_limited"]
    error: str | None
    sent_at: datetime
    model_config = {"from_attributes": True}


# ---------- Exceptions (used by sender → router) ----------

class CloneRateLimitedError(Exception):
    def __init__(self, retry_after_sec: int) -> None:
        super().__init__(f"Rate limited — retry after {retry_after_sec}s")
        self.retry_after_sec = retry_after_sec


class HostConfigMissingError(Exception):
    pass
