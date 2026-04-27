from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ProxyScheme = Literal["socks5", "http", "https"]


class ProxyCreate(BaseModel):
    scheme: ProxyScheme
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=255)


class ProxyUpdate(BaseModel):
    scheme: ProxyScheme | None = None
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=255)


class ProxyOut(BaseModel):
    id: int
    scheme: ProxyScheme
    host: str
    port: int
    username: str | None
    note: str | None
    created_at: datetime
    used_by_count: int = 0
    model_config = {"from_attributes": True}


class ProxyImportRequest(BaseModel):
    scheme: ProxyScheme
    raw_text: str = Field(min_length=1, max_length=200_000)


class ProxyImportError(BaseModel):
    line: int
    raw: str
    reason: str


class ProxyImportResult(BaseModel):
    created: int
    skipped_duplicates: int
    errors: list[ProxyImportError]


class ProxyAssignRequest(BaseModel):
    only_unassigned: bool = False


class ProxyAssignResult(BaseModel):
    assigned: int
    reason: Literal["ok", "no_proxies", "no_clones", "all_assigned"]


class RequireProxySetting(BaseModel):
    require_proxy: bool
