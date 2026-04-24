from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


AiKeyMode = Literal["own", "system"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=1)


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    max_nicks: int | None
    is_locked: bool
    ai_key_mode: AiKeyMode
    created_at: datetime

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=100)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=8, max_length=100)
    max_nicks: int | None = Field(default=None, ge=0)
    ai_key_mode: AiKeyMode = "system"


class UserUpdate(BaseModel):
    max_nicks: int | None = Field(default=None, ge=0)
    is_locked: bool | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=100)
    ai_key_mode: AiKeyMode | None = None
