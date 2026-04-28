import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.database import SessionLocal, get_db
from app.models.nick_live import NickLive
from app.models.reply_log import ReplyLog
from app.schemas.nick_live import (
    AutoPostStartRequest,
    BatchSessionEntry,
    BatchSessionsResponse,
    HostPostRequest,
    LiveSession,
    LiveSessionsResponse,
    NickLiveCreate,
    NickLiveResponse,
    NickLiveUpdateCookies,
    ScanStats,
    ScanStatus,
)
from app.schemas.nick_live import (
    ModeratorAutoReplyRequest,
    ModeratorReplyRequest,
    ModeratorSaveCurlRequest,
    ModeratorStatus,
)
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.settings import (
    AutoPinStartRequest,
    AutoPostTemplateCreate,
    AutoPostTemplateResponse,
    AutoPostTemplateUpdate,
    NickLiveSettingsResponse,
    NickLiveSettingsUpdate,
    ReplyTemplateCreate,
    ReplyTemplateResponse,
)
from app.services.relive_service import get_host_credentials
from app.services.comment_scanner import scanner
from app.services.live_moderator import moderator
from app.services.settings_service import SettingsService
from app.services.shopee_api import get_live_sessions

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/nick-lives",
    tags=["nick-lives"],
)


def _owned_nick_or_404(db: Session, nick_live_id: int, user_id: int) -> NickLive:
    """Return the NickLive if it belongs to user_id, else raise 404."""
    nick = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == user_id
    ).first()
    if not nick:
        raise HTTPException(status_code=404, detail="Nick not found")
    return nick


@router.post("", response_model=NickLiveResponse)
def create_nick_live(
    payload: NickLiveCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NickLive:
    # Enforce quota
    if current_user.max_nicks is not None:
        n = db.query(NickLive).filter(NickLive.user_id == current_user.id).count()
        if n >= current_user.max_nicks:
            raise HTTPException(
                status_code=403,
                detail=f"Nick quota exceeded (max {current_user.max_nicks})",
            )

    # Support both flat and nested create forms
    if payload.user is not None:
        name = payload.user.name
        shopee_user_id = payload.user.id
        shop_id = payload.user.shop_id
        avatar = payload.user.avatar
    else:
        name = payload.name or ""
        shopee_user_id = payload.shopee_user_id or 0
        shop_id = payload.shop_id
        avatar = payload.avatar

    nick = NickLive(
        user_id=current_user.id,
        name=name,
        shopee_user_id=shopee_user_id,
        shop_id=shop_id,
        avatar=avatar,
        cookies=payload.cookies,
    )
    db.add(nick)
    db.commit()
    db.refresh(nick)
    return nick


@router.get("", response_model=list[NickLiveResponse])
def list_nick_lives(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[NickLive]:
    return (
        db.query(NickLive)
        .filter(NickLive.user_id == current_user.id)
        .order_by(NickLive.created_at.desc())
        .all()
    )


@router.get("/{nick_live_id}/cookies")
def get_nick_cookies(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Return the current cookies string for this nick (owner only)."""
    nick = _owned_nick_or_404(db, nick_live_id, current_user.id)
    return {"cookies": nick.cookies or ""}


@router.patch("/{nick_live_id}/cookies", response_model=NickLiveResponse)
def update_nick_cookies(
    nick_live_id: int,
    payload: NickLiveUpdateCookies,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NickLive:
    """Update cookies for an existing nick live.

    If the scanner is running, it is restarted with the new cookies on the
    same session so the poll loop picks up the fresh auth.
    """
    nick = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == current_user.id
    ).first()
    if not nick:
        raise HTTPException(status_code=404, detail="NickLive not found")

    nick.cookies = payload.cookies
    if payload.user is not None:
        nick.name = payload.user.name
        nick.shopee_user_id = payload.user.id
        nick.shop_id = payload.user.shop_id
        nick.avatar = payload.user.avatar
    db.commit()
    db.refresh(nick)

    from app.services.nick_cache import nick_cache
    nick_cache.invalidate(nick_live_id)

    status = scanner.get_status(nick_live_id)
    if status.get("is_scanning") and status.get("session_id"):
        session_id = status["session_id"]
        scanner.stop(nick_live_id)
        scanner.start(nick_live_id, session_id, nick.cookies)
        logger.info(
            "Restarted scanner for nick %s on session %s with fresh cookies",
            nick_live_id,
            session_id,
        )

    return nick


@router.delete("/{nick_live_id}")
def delete_nick_live(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    nick = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == current_user.id
    ).first()
    if not nick:
        raise HTTPException(status_code=404, detail="NickLive not found")
    # Stop scanning if running
    scanner.stop(nick_live_id)
    from app.services.nick_cache import nick_cache
    nick_cache.invalidate(nick_live_id)
    db.delete(nick)
    db.commit()
    return {"detail": "Deleted"}


@router.get("/sessions", response_model=BatchSessionsResponse)
async def list_sessions_batch(
    ids: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BatchSessionsResponse:
    """Batch-fetch sessions for multiple owned nicks. Throttles 200ms between calls."""
    raw = [s.strip() for s in ids.split(",") if s.strip()]
    if not raw:
        return BatchSessionsResponse(sessions={})
    try:
        nick_ids = [int(s) for s in raw]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids must be comma-separated integers")

    owned = (
        db.query(NickLive)
        .filter(NickLive.id.in_(nick_ids), NickLive.user_id == current_user.id)
        .all()
    )

    result: dict[str, BatchSessionEntry] = {}
    for idx, nick in enumerate(owned):
        if idx > 0:
            await asyncio.sleep(0.2)
        try:
            data = await get_live_sessions(nick.cookies)
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
            result[str(nick.id)] = BatchSessionEntry(active_session=active, all_sessions=sessions)
        except Exception as e:
            result[str(nick.id)] = BatchSessionEntry(error=str(e))

    return BatchSessionsResponse(sessions=result)


@router.get("/{nick_live_id}/sessions", response_model=LiveSessionsResponse)
async def get_sessions(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LiveSessionsResponse:
    nick = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == current_user.id
    ).first()
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
async def start_scan(
    nick_live_id: int,
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    nick = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == current_user.id
    ).first()
    if not nick:
        raise HTTPException(status_code=404, detail="NickLive not found")

    if scanner.is_scanning(nick_live_id):
        raise HTTPException(status_code=400, detail="Already scanning")

    scanner.start(nick_live_id, session_id, nick.cookies)
    return {"detail": "Scanning started", "session_id": session_id}


@router.post("/{nick_live_id}/scan/stop")
def stop_scan(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    scanner.stop(nick_live_id)
    return {"detail": "Scanning stopped"}


@router.get("/{nick_live_id}/scan/status", response_model=ScanStatus)
def scan_status(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScanStatus:
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    status = scanner.get_status(nick_live_id)
    return ScanStatus(**status)


@router.get("/{nick_live_id}/scan-stats", response_model=ScanStats)
def scan_stats(
    nick_live_id: int,
    window: int = 300,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScanStats:
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    if window <= 0 or window > 3600:
        raise HTTPException(status_code=400, detail="window must be between 1 and 3600")

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window)
    rows = (
        db.query(ReplyLog.outcome)
        .filter(ReplyLog.nick_live_id == nick_live_id, ReplyLog.created_at >= cutoff)
        .all()
    )
    ok = sum(1 for (o,) in rows if o == "success")
    fail = sum(1 for (o,) in rows if o == "failed")
    dropped = sum(1 for (o,) in rows if o == "dropped")

    comments_new = scanner.get_comments_in_window(nick_live_id, window)
    return ScanStats(
        comments_new=comments_new,
        replies_ok=ok,
        replies_fail=fail,
        replies_dropped=dropped,
        window_seconds=window,
    )


@router.get("/{nick_live_id}/comments")
def get_all_comments(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list:
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    return scanner.get_comments(nick_live_id)


@router.get("/{nick_live_id}/comments/stream")
async def stream_comments(
    nick_live_id: int,
    current_user: User = Depends(get_current_user),
) -> EventSourceResponse:
    """SSE endpoint - streams new comments as they arrive."""
    # Open a short-lived session just to validate ownership; do NOT hold a DB
    # connection for the lifetime of the SSE stream (which can run for hours
    # and would exhaust the connection pool).
    with SessionLocal() as db:
        _owned_nick_or_404(db, nick_live_id, current_user.id)

    async def event_generator():
        queue = scanner.subscribe(nick_live_id)
        try:
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
        finally:
            scanner.unsubscribe(nick_live_id, queue)

    return EventSourceResponse(event_generator())


# --- Moderator endpoints ---


@router.post("/{nick_live_id}/moderator/save-curl")
async def save_moderator_curl(
    nick_live_id: int,
    payload: ModeratorSaveCurlRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Save moderator cURL template for this nick_live."""
    nick = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == current_user.id
    ).first()
    if not nick:
        raise HTTPException(status_code=404, detail="NickLive not found")
    result = moderator.save_curl(nick_live_id, payload.curl_text)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/{nick_live_id}/moderator/status", response_model=ModeratorStatus)
async def get_moderator_status(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ModeratorStatus:
    """Check if moderator is configured for this nick_live."""
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    config = moderator.get_config(nick_live_id)
    return ModeratorStatus(
        nick_live_id=nick_live_id,
        configured=config is not None,
        host_id=config.get("host_id") if config else None,
        has_usersig=bool(config.get("usersig")) if config else False,
    )


@router.delete("/{nick_live_id}/moderator")
async def remove_moderator(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Remove moderator config for this nick_live."""
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    if moderator.remove_config(nick_live_id):
        return {"detail": "Removed"}
    raise HTTPException(status_code=404, detail="Moderator not configured")


@router.post("/{nick_live_id}/moderator/reply")
async def send_moderator_reply(
    nick_live_id: int,
    payload: ModeratorReplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Send a single reply. Uses the active live session_id from scanner."""
    _owned_nick_or_404(db, nick_live_id, current_user.id)
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
    nick_live_id: int,
    payload: ModeratorAutoReplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Auto-reply to multiple comments. Uses the active live session_id."""
    _owned_nick_or_404(db, nick_live_id, current_user.id)
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
def get_nick_settings(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    nick = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == current_user.id
    ).first()
    if not nick:
        raise HTTPException(status_code=404, detail="Nick not found")
    svc = SettingsService(db, user_id=current_user.id)
    row = svc.get_or_create_nick_settings(nick_live_id)
    return row


@router.put("/{nick_live_id}/settings", response_model=NickLiveSettingsResponse)
def update_nick_settings(
    nick_live_id: int,
    payload: NickLiveSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    nick = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == current_user.id
    ).first()
    if not nick:
        raise HTTPException(status_code=404, detail="Nick not found")
    svc = SettingsService(db, user_id=current_user.id)
    try:
        row = svc.update_nick_settings(
            nick_live_id,
            reply_mode=payload.reply_mode,
            reply_to_host=payload.reply_to_host,
            reply_to_moderator=payload.reply_to_moderator,
            auto_post_enabled=payload.auto_post_enabled,
            auto_post_to_host=payload.auto_post_to_host,
            auto_post_to_moderator=payload.auto_post_to_moderator,
            host_proxy=payload.host_proxy,
            auto_pin_enabled=payload.auto_pin_enabled,
            pin_min_interval_minutes=payload.pin_min_interval_minutes,
            pin_max_interval_minutes=payload.pin_max_interval_minutes,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Invalidate cached per-nick settings so the dispatcher picks up the
    # new toggles on its next reply cycle.
    from app.services.nick_cache import nick_cache
    nick_cache.invalidate_settings(nick_live_id)
    return row


# --- Host config endpoints ---


@router.post("/{nick_live_id}/host/get-credentials")
async def host_get_credentials(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch usersig+uuid from relive.vn, save to host_config."""
    nick = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == current_user.id
    ).first()
    if not nick:
        raise HTTPException(status_code=404, detail="NickLive not found")

    svc = SettingsService(db, user_id=current_user.id)
    api_key = svc.get_system_relive_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="Relive API key not configured")

    nick_settings = svc.get_or_create_nick_settings(nick_live_id)
    proxy = getattr(nick_settings, "host_proxy", None)

    debug: dict = {}  # DEBUG_RELIVE
    try:
        creds = await get_host_credentials(nick.cookies, api_key, proxy=proxy, debug=debug)
    except ValueError as exc:
        logger.error("host_get_credentials failed for nick %s: %s", nick_live_id, exc)
        # DEBUG_RELIVE: surface debug dict so FE can log it
        raise HTTPException(status_code=502, detail={"message": str(exc), "debug": debug})

    svc.save_host_config(nick_live_id, creds["usersig"], creds["uuid"])
    moderator.save_host_config(nick_live_id, creds["usersig"], creds["uuid"])

    return {"status": "ok", "uuid": creds["uuid"], "debug": debug}  # DEBUG_RELIVE


@router.get("/{nick_live_id}/host/status")
def host_status(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return host config status."""
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    svc = SettingsService(db, user_id=current_user.id)
    config = svc.get_host_config(nick_live_id)
    return {
        "configured": config is not None,
        "uuid": config.get("uuid") if config else None,
        "has_usersig": bool(config.get("usersig")) if config else False,
    }


# --- Auto-post endpoints ---


@router.post("/{nick_live_id}/auto-post/start")
async def auto_post_start(
    nick_live_id: int,
    payload: AutoPostStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start auto-post loop."""
    nick = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == current_user.id
    ).first()
    if not nick:
        raise HTTPException(status_code=404, detail="NickLive not found")

    from app.main import auto_poster
    result = await auto_poster.start(nick_live_id, payload.session_id, nick.cookies)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{nick_live_id}/auto-post/stop")
async def auto_post_stop(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stop auto-post loop."""
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    from app.main import auto_poster
    result = await auto_poster.stop(nick_live_id)
    return result


@router.get("/{nick_live_id}/auto-post/status")
def auto_post_status(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check if auto-post is running."""
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    from app.main import auto_poster
    return {"running": auto_poster.is_running(nick_live_id)}


# --- Auto-pin control ---


@router.post("/{nick_live_id}/auto-pin/start")
async def auto_pin_start(
    nick_live_id: int,
    payload: AutoPinStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start auto-pin loop for this nick."""
    nick = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == current_user.id
    ).first()
    if not nick:
        raise HTTPException(status_code=404, detail="NickLive not found")

    from app.main import auto_pinner
    if auto_pinner is None:
        raise HTTPException(status_code=503, detail="Auto-pin service not ready")

    result = await auto_pinner.start(nick_live_id, payload.session_id, nick.cookies)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{nick_live_id}/auto-pin/stop")
async def auto_pin_stop(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stop auto-pin loop for this nick."""
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    from app.main import auto_pinner
    if auto_pinner is None:
        return {"status": "not_running"}
    return await auto_pinner.stop(nick_live_id)


@router.get("/{nick_live_id}/auto-pin/status")
def auto_pin_status(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check if auto-pin is running."""
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    from app.main import auto_pinner
    running = auto_pinner.is_running(nick_live_id) if auto_pinner is not None else False
    return {"running": running}


# --- Manual host comment ---


@router.post("/{nick_live_id}/host/post")
async def host_post(
    nick_live_id: int,
    payload: HostPostRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manual host comment (type 101)."""
    nick = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == current_user.id
    ).first()
    if not nick:
        raise HTTPException(status_code=404, detail="NickLive not found")

    if not moderator.has_host_config(nick_live_id):
        raise HTTPException(status_code=400, detail="Host not configured")

    body = moderator.generate_host_post_body(nick_live_id, payload.content)
    if not body:
        raise HTTPException(status_code=400, detail="Failed to generate host message body")

    result = await moderator.send_host_message(
        nick_live_id, payload.session_id, body, nick.cookies
    )
    return result


# --- Per-nick auto-post template CRUD ---


@router.get(
    "/{nick_live_id}/auto-post-templates",
    response_model=list[AutoPostTemplateResponse],
)
def list_nick_auto_post_templates(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    svc = SettingsService(db, user_id=current_user.id)
    return svc.get_auto_post_templates_for_nick(nick_live_id)


@router.post(
    "/{nick_live_id}/auto-post-templates",
    response_model=AutoPostTemplateResponse,
)
def create_nick_auto_post_template(
    nick_live_id: int,
    payload: AutoPostTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    svc = SettingsService(db, user_id=current_user.id)
    return svc.create_auto_post_template_for_nick(
        nick_live_id,
        payload.content,
        payload.min_interval_seconds,
        payload.max_interval_seconds,
    )


@router.put(
    "/{nick_live_id}/auto-post-templates/{template_id}",
    response_model=AutoPostTemplateResponse,
)
def update_nick_auto_post_template(
    nick_live_id: int,
    template_id: int,
    payload: AutoPostTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    svc = SettingsService(db, user_id=current_user.id)
    result = svc.update_auto_post_template(
        template_id,
        nick_live_id=nick_live_id,
        content=payload.content,
        min_interval=payload.min_interval_seconds,
        max_interval=payload.max_interval_seconds,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Template not found")
    return result


@router.delete("/{nick_live_id}/auto-post-templates/{template_id}")
def delete_nick_auto_post_template(
    nick_live_id: int,
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    svc = SettingsService(db, user_id=current_user.id)
    if not svc.delete_auto_post_template_for_nick(nick_live_id, template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"detail": "Deleted"}


# --- Per-nick reply template CRUD ---


@router.get(
    "/{nick_live_id}/reply-templates",
    response_model=list[ReplyTemplateResponse],
)
def list_nick_reply_templates(
    nick_live_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    svc = SettingsService(db, user_id=current_user.id)
    return svc.get_reply_templates_for_nick(nick_live_id)


@router.post(
    "/{nick_live_id}/reply-templates",
    response_model=ReplyTemplateResponse,
)
def create_nick_reply_template(
    nick_live_id: int,
    payload: ReplyTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    svc = SettingsService(db, user_id=current_user.id)
    return svc.create_reply_template_for_nick(nick_live_id, payload.content)


@router.delete("/{nick_live_id}/reply-templates/{template_id}")
def delete_nick_reply_template(
    nick_live_id: int,
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_nick_or_404(db, nick_live_id, current_user.id)
    svc = SettingsService(db, user_id=current_user.id)
    if not svc.delete_reply_template_for_nick(nick_live_id, template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"detail": "Deleted"}
