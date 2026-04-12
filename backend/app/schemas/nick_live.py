from datetime import datetime

from pydantic import BaseModel


class NickLiveCreate(BaseModel):
    """User pastes JSON with user object + cookies string"""

    user: dict  # contains id, name, shop_id, avatar etc.
    cookies: str


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
    curl_text: str


class ModeratorReplyRequest(BaseModel):
    """Send a reply to a specific guest."""
    guest_name: str
    guest_id: int
    reply_text: str


class ModeratorAutoReplyRequest(BaseModel):
    """Auto-reply to multiple comments."""
    comments: list[dict]
    reply_text: str


class ModeratorStatus(BaseModel):
    """Whether moderator is configured for a nick_live."""
    nick_live_id: int
    configured: bool
    host_id: str | None = None
    has_usersig: bool = False
