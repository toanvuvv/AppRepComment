import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import REPLY_LOG_CLEANUP_INTERVAL_SEC, REPLY_LOG_RETENTION_HOURS
from app.database import SessionLocal, get_db, init_db
from app.models.reply_log import ReplyLog
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.health import router as health_router
from app.routers.knowledge import router as knowledge_router
from app.routers.nick_live import router as nick_live_router
from app.routers.reply_logs import router as reply_logs_router
from app.routers.seeding import router as seeding_router
from app.routers.seeding_proxy import router as seeding_proxy_router
from app.routers.settings import router as settings_router

logger = logging.getLogger(__name__)

# Module-level references; initialised inside lifespan().
auto_poster: "AutoPoster | None" = None  # noqa: F821
auto_pinner: "AutoPinner | None" = None  # noqa: F821


def _delete_logs_before(cutoff: datetime) -> int:
    """Delete reply_log rows older than ``cutoff``. Returns deleted count."""
    with SessionLocal() as db:
        n = db.query(ReplyLog).filter(ReplyLog.created_at < cutoff).delete()
        db.commit()
        return int(n or 0)


async def _reply_log_cleanup_loop() -> None:
    """Periodically delete reply_log rows older than REPLY_LOG_RETENTION_HOURS."""
    while True:
        try:
            await asyncio.sleep(REPLY_LOG_CLEANUP_INTERVAL_SEC)
            cutoff = datetime.now(timezone.utc) - timedelta(
                hours=REPLY_LOG_RETENTION_HOURS
            )
            deleted = await asyncio.to_thread(_delete_logs_before, cutoff)
            logger.info(
                f"reply_log cleanup: deleted {deleted} rows older than {cutoff}"
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("reply_log cleanup error")


_SEEDING_LOG_RETENTION_DAYS = 30
_SEEDING_LOG_CLEANUP_INTERVAL_SEC = 3600


async def _seeding_log_cleanup_loop() -> None:
    """Periodically delete seeding_logs/seeding_log_sessions older than 30 days."""
    from app.services.seeding_log_retention import cleanup_old_seeding_logs

    while True:
        try:
            await asyncio.sleep(_SEEDING_LOG_CLEANUP_INTERVAL_SEC)
            await asyncio.to_thread(
                cleanup_old_seeding_logs, _SEEDING_LOG_RETENTION_DAYS
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("seeding_log cleanup loop error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Load persisted moderator configs into memory cache
    from app.services.live_moderator import moderator
    moderator.load_all_from_db()

    # Initialise auto-poster (depends on moderator being loaded)
    from app.services.auto_poster import AutoPoster
    global auto_poster
    auto_poster = AutoPoster(moderator)

    # Initialise auto-pinner
    from app.services.auto_pinner import AutoPinner
    global auto_pinner
    auto_pinner = AutoPinner()

    # Start reply log writer background task
    from app.services.reply_log_writer import reply_log_writer
    await reply_log_writer.start()

    # Start hourly cleanup task for reply_logs retention.
    cleanup_task = asyncio.create_task(
        _reply_log_cleanup_loop(), name="reply-log-cleanup"
    )
    seeding_cleanup_task = asyncio.create_task(
        _seeding_log_cleanup_loop(), name="seeding-log-cleanup"
    )

    try:
        yield
    finally:
        # Shutdown sequence.
        cleanup_task.cancel()
        seeding_cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("reply_log cleanup task shutdown error")
        try:
            await seeding_cleanup_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("seeding_log cleanup task shutdown error")

        await reply_log_writer.stop()

        # Stop all auto-post loops.
        if auto_poster is not None:
            auto_poster.stop_all()

        # Stop all auto-pin loops.
        if auto_pinner is not None:
            auto_pinner.stop_all()

        # Close shared httpx client on shutdown so we don't leak sockets.
        from app.services.http_client import close_client
        await close_client()


is_dev = os.getenv("ENV", "development") == "development"

app = FastAPI(
    title="App Rep Comment",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if is_dev else None,
    redoc_url="/redoc" if is_dev else None,
)

from app.rate_limit import limiter

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
def _rate_limit_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many attempts, try again later"},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(nick_live_router)
app.include_router(settings_router)
app.include_router(knowledge_router)
app.include_router(health_router)
app.include_router(reply_logs_router)
app.include_router(seeding_router)
app.include_router(seeding_proxy_router)


@app.get("/api/health")
@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.warning("healthcheck DB probe failed", exc_info=True)
        return Response(
            status_code=503,
            content='{"status":"db_error"}',
            media_type="application/json",
        )
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
