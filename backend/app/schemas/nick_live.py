from datetime import datetime

from pydantic import BaseModel, Field


class UserPayload(BaseModel):
    id: int
    name: str = Field(max_length=100)
    shop_id: int | None = None
    avatar: str | None = Field(default=None, max_length=500)


class NickLiveCreate(BaseModel):
    """User pastes JSON with user object + cookies string"""

    user: UserPayload
    cookies: str = Field(min_length=1, max_length=20000)


class NickLiveResponse(BaseModel):
    id: int
    name: str
    user_id: int
    shop_id: int | None
    avatar: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class LiveSession(BaseModel):
    sessionId: int
    title: str
    coverImage: str
    startTime: int
    duration: int
    status: int
    views: int
    viewers: int
    peakViewers: int
    comments: int
    # status=1 and duration=0 means currently live


class LiveSessionsResponse(BaseModel):
    sessions: list[LiveSession]
    active_session: LiveSession | None  # the one with duration=0 and status=1


class CommentItem(BaseModel):
    id: str | None = None
    userName: str | None = None
    username: str | None = None
    nick_name: str | None = None
    nickname: str | None = None
    content: str | None = None
    comment: str | None = None
    message: str | None = None
    msg: str | None = None
    timestamp: int | None = None
    create_time: int | None = None
    ctime: int | None = None


class ScanStatus(BaseModel):
    is_scanning: bool
    session_id: int | None = None
    comment_count: int = 0


# --- Moderator schemas ---


class ModeratorSaveCurlRequest(BaseModel):
    """Save moderator cURL template for a nick_live."""

    curl_text: str = Field(min_length=10, max_length=50000)


class ModeratorReplyRequest(BaseModel):
    """Send a reply to a specific guest."""

    guest_name: str = Field(min_length=1, max_length=200)
    guest_id: int
    reply_text: str = Field(min_length=1, max_length=2000)


class ModeratorAutoReplyRequest(BaseModel):
    """Auto-reply to multiple comments."""

    comments: list[dict]
    reply_text: str = Field(min_length=1, max_length=2000)


class ModeratorStatus(BaseModel):
    """Whether moderator is configured for a nick_live."""

    nick_live_id: int
    configured: bool
    host_id: str | None = None
    has_usersig: bool = False


# --- Host schemas ---


class HostGetCredentialsResponse(BaseModel):
    status: str
    uuid: str | None = None
    error: str | None = None


class HostConfigStatus(BaseModel):
    configured: bool
    uuid: str | None = None
    has_usersig: bool = False
    proxy: str | None = None


class AutoPostStartRequest(BaseModel):
    session_id: int


class AutoPostStatusResponse(BaseModel):
    running: bool


class HostPostRequest(BaseModel):
    """Manual host comment (type 101)."""

    content: str = Field(..., min_length=1, max_length=2000)
    session_id: int
