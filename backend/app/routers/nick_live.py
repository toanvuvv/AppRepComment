import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.database import get_db
from app.models.nick_live import NickLive
from app.schemas.nick_live import (
    LiveSession,
    LiveSessionsResponse,
    NickLiveCreate,
    NickLiveResponse,
    ScanStatus,
)
from app.schemas.nick_live import (
    ModeratorAutoReplyRequest,
    ModeratorReplyRequest,
    ModeratorSaveCurlRequest,
    ModeratorStatus,
)
from app.dependencies import require_api_key
from app.schemas.settings import NickLiveSettingsResponse, NickLiveSettingsUpdate
from app.services.comment_scanner import scanner
from app.services.live_moderator import moderator
from app.services.settings_service import SettingsService
from app.services.shopee_api import get_live_sessions

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/nick-lives",
    tags=["nick-lives"],
    dependencies=[Depends(require_api_key)],
)


@router.post("", response_model=NickLiveResponse)
def create_nick_live(payload: NickLiveCreate, db: Session = Depends(get_db)) -> NickLive:
    user_data = payload.user
    nick = NickLive(
        name=user_data.name,
        user_id=user_data.id,
        shop_id=user_data.shop_id,
        avatar=user_data.avatar,
        cookies=payload.cookies,
    )
    db.add(nick)
    db.commit()
    db.refresh(nick)
    return nick


@router.get("", response_model=list[NickLiveResponse])
def list_nick_lives(db: Session = Depends(get_db)) -> list[NickLive]:
    return db.query(NickLive).order_by(NickLive.created_at.desc()).all()


@router.delete("/{nick_live_id}")
def delete_nick_live(nick_live_id: int, db: Session = Depends(get_db)) -> dict:
    nick = db.query(NickLive).filter(NickLive.id == nick_live_id).first()
    if not nick:
        raise HTTPException(status_code=404, detail="NickLive not found")
    # Stop scanning if running
    scanner.stop(nick_live_id)
    db.delete(nick)
    db.commit()
    return {"detail": "Deleted"}


@router.get("/{nick_live_id}/sessions", response_model=LiveSessionsResponse)
async def get_sessions(nick_live_id: int, db: Session = Depends(get_db)) -> LiveSessionsResponse:
    nick = db.query(NickLive).filter(NickLive.id == nick_live_id).first()
    if not nick:
        raise HTTPException(status_code=404, detail="NickLive not found")

    try:
        data = await get_live_sessions(nick.cookies)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Shopee API error: {e}")

    sessions_data = data.get("data", {}).get("list", [])
    sessions: list[LiveSession] = []
    active: LiveSession | None = None
    for s in sessions_data:
        session = LiveSession(
            sessionId=s["sessionId"],
            title=s.get("title", ""),
            coverImage=s.get("coverImage", ""),
            startTime=s.get("startTime", 0),
            duration=s.get("duration", 0),
            status=s.get("status", 0),
            views=s.get("views", 0),
            viewers=s.get("viewers", 0),
            peakViewers=s.get("peakViewers", 0),
            comments=s.get("comments", 0),
        )
        sessions.append(session)
        if session.status == 1 and session.duration == 0:
            active = session

    return LiveSessionsResponse(sessions=sessions, active_session=active)


@router.post("/{nick_live_id}/scan/start")
async def start_scan(nick_live_id: int, session_id: int, db: Session = Depends(get_db)) -> dict:
    nick = db.query(NickLive).filter(NickLive.id == nick_live_id).first()
    if not nick:
        raise HTTPException(status_code=404, detail="NickLive not found")

    if scanner.is_scanning(nick_live_id):
        raise HTTPException(status_code=400, detail="Already scanning")

    scanner.start(nick_live_id, session_id, nick.cookies)
    return {"detail": "Scanning started", "session_id": session_id}


@router.post("/{nick_live_id}/scan/stop")
def stop_scan(nick_live_id: int) -> dict:
    scanner.stop(nick_live_id)
    return {"detail": "Scanning stopped"}


@router.get("/{nick_live_id}/scan/status", response_model=ScanStatus)
def scan_status(nick_live_id: int) -> ScanStatus:
    status = scanner.get_status(nick_live_id)
    return ScanStatus(**status)


@router.get("/{nick_live_id}/comments")
def get_all_comments(nick_live_id: int) -> list:
    return scanner.get_comments(nick_live_id)


@router.get("/{nick_live_id}/comments/stream")
async def stream_comments(nick_live_id: int) -> EventSourceResponse:
    """SSE endpoint - streams new comments as they arrive"""
    queue = scanner.get_queue(nick_live_id)

    async def event_generator():
        while True:
            try:
                comment = await asyncio.wait_for(queue.get(), timeout=30.0)
                if comment is None:
                    break
                yield {
                    "event": "comment",
                    "data": json.dumps(comment, ensure_ascii=False),
                }
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": ""}

    return EventSourceResponse(event_generator())


# --- Moderator endpoints ---


@router.post("/{nick_live_id}/moderator/save-curl")
async def save_moderator_curl(
    nick_live_id: int, payload: ModeratorSaveCurlRequest, db: Session = Depends(get_db)
) -> dict:
    """Save moderator cURL template for this nick_live."""
    nick = db.query(NickLive).filter(NickLive.id == nick_live_id).first()
    if not nick:
        raise HTTPException(status_code=404, detail="NickLive not found")
    result = moderator.save_curl(nick_live_id, payload.curl_text)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/{nick_live_id}/moderator/status", response_model=ModeratorStatus)
async def get_moderator_status(nick_live_id: int) -> ModeratorStatus:
    """Check if moderator is configured for this nick_live."""
    config = moderator.get_config(nick_live_id)
    return ModeratorStatus(
        nick_live_id=nick_live_id,
        configured=config is not None,
        host_id=config.get("host_id") if config else None,
        has_usersig=bool(config.get("usersig")) if config else False,
    )


@router.delete("/{nick_live_id}/moderator")
async def remove_moderator(nick_live_id: int) -> dict:
    """Remove moderator config for this nick_live."""
    if moderator.remove_config(nick_live_id):
        return {"detail": "Removed"}
    raise HTTPException(status_code=404, detail="Moderator not configured")


@router.post("/{nick_live_id}/moderator/reply")
async def send_moderator_reply(
    nick_live_id: int, payload: ModeratorReplyRequest
) -> dict:
    """Send a single reply. Uses the active live session_id from scanner."""
    if not moderator.has_config(nick_live_id):
        raise HTTPException(status_code=400, detail="Moderator not configured")
    scan_status = scanner.get_status(nick_live_id)
    if not scan_status["is_scanning"] or not scan_status.get("session_id"):
        raise HTTPException(
            status_code=400, detail="No active live session being scanned"
        )
    live_session_id = scan_status["session_id"]
    result = await moderator.send_reply(
        nick_live_id,
        live_session_id,
        payload.guest_name,
        payload.guest_id,
        payload.reply_text,
    )
    return result


@router.post("/{nick_live_id}/moderator/auto-reply")
async def auto_reply_comments(
    nick_live_id: int, payload: ModeratorAutoReplyRequest
) -> list[dict]:
    """Auto-reply to multiple comments. Uses the active live session_id."""
    if not moderator.has_config(nick_live_id):
        raise HTTPException(status_code=400, detail="Moderator not configured")
    scan_status = scanner.get_status(nick_live_id)
    if not scan_status["is_scanning"] or not scan_status.get("session_id"):
        raise HTTPException(
            status_code=400, detail="No active live session being scanned"
        )
    live_session_id = scan_status["session_id"]
    return await moderator.auto_reply_comments(
        nick_live_id, live_session_id, payload.comments, payload.reply_text
    )


# --- Nick live settings (per-nick AI toggles) ---


@router.get("/{nick_live_id}/settings", response_model=NickLiveSettingsResponse)
def get_nick_settings(nick_live_id: int, db: Session = Depends(get_db)):
    svc = SettingsService(db)
    row = svc.get_or_create_nick_settings(nick_live_id)
    return row


@router.put("/{nick_live_id}/settings", response_model=NickLiveSettingsResponse)
def update_nick_settings(
    nick_live_id: int, payload: NickLiveSettingsUpdate, db: Session = Depends(get_db)
):
    svc = SettingsService(db)
    row = svc.update_nick_settings(
        nick_live_id,
        ai_reply_enabled=payload.ai_reply_enabled,
        auto_reply_enabled=payload.auto_reply_enabled,
        auto_post_enabled=payload.auto_post_enabled,
        knowledge_reply_enabled=payload.knowledge_reply_enabled,
    )
    return row
