"""Auto-post worker: rotates through per-nick templates on a schedule."""

import asyncio
import logging
import random
from typing import Any

from app.database import SessionLocal
from app.services.live_moderator import ShopeeLiveModerator
from app.services.reply_log_writer import reply_log_writer
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


class AutoPoster:
    def __init__(self, moderator: ShopeeLiveModerator) -> None:
        self._moderator = moderator
        self._tasks: dict[int, asyncio.Task] = {}
        self._template_index: dict[int, int] = {}

    def is_running(self, nick_live_id: int) -> bool:
        task = self._tasks.get(nick_live_id)
        return task is not None and not task.done()

    async def start(
        self, nick_live_id: int, session_id: int, cookies: str,
    ) -> dict[str, Any]:
        if self.is_running(nick_live_id):
            return {"status": "already_running"}

        # Read per-nick settings (auto_post_enabled + channel toggles).
        from app.services.nick_cache import nick_cache
        settings = await nick_cache.get_settings(nick_live_id, SessionLocal)

        if not settings.auto_post_enabled:
            return {"error": "Auto post chưa được bật"}

        if not settings.auto_post_to_host and not settings.auto_post_to_moderator:
            return {"error": "Cần bật ít nhất 1 kênh (Host hoặc Moderator) cho Auto Post"}

        if settings.auto_post_to_host and not self._moderator.has_host_config(nick_live_id):
            return {"error": "Chưa cấu hình host credentials cho Auto Post Host"}
        if settings.auto_post_to_moderator and not self._moderator.has_config(nick_live_id):
            return {"error": "Chưa cấu hình moderator cURL cho Auto Post Moderator"}

        db = SessionLocal()
        try:
            svc = SettingsService(db)
            templates = svc.get_auto_post_templates_for_nick(nick_live_id)
        finally:
            db.close()

        if not templates:
            return {"error": "Chưa có template auto-post cho nick này"}

        self._template_index[nick_live_id] = 0
        task = asyncio.create_task(self._loop(nick_live_id, session_id, cookies))
        self._tasks[nick_live_id] = task
        logger.info(f"Auto-post started for nick={nick_live_id}")
        return {"status": "started"}

    async def stop(self, nick_live_id: int) -> dict[str, Any]:
        task = self._tasks.pop(nick_live_id, None)
        self._template_index.pop(nick_live_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info(f"Auto-post stopped for nick={nick_live_id}")
            return {"status": "stopped"}
        return {"status": "not_running"}

    def stop_all(self) -> None:
        for nick_id in list(self._tasks):
            task = self._tasks.pop(nick_id)
            if not task.done():
                task.cancel()
        self._template_index.clear()

    def _user_nick_ids(self, user_id: int) -> list[int]:
        from app.database import SessionLocal
        from app.models.nick_live import NickLive
        with SessionLocal() as db:
            return [nid for (nid,) in db.query(NickLive.id)
                    .filter(NickLive.user_id == user_id).all()]

    def stop_user_nicks(self, user_id: int) -> None:
        """Stop all running auto-post loops for nicks owned by user_id."""
        for nid in self._user_nick_ids(user_id):
            task = self._tasks.pop(nid, None)
            self._template_index.pop(nid, None)
            if task and not task.done():
                task.cancel()
                logger.info(f"Auto-post stopped (lock) for nick={nid} user={user_id}")

    def start_user_nicks(self, user_id: int) -> None:
        """Re-start auto-post loops is intentionally a no-op on unlock.

        Re-starting requires session_id and cookies which are not available
        at lock/unlock time. The frontend will re-trigger auto-post start
        explicitly when needed. This method exists as a hook for future use.
        """
        logger.info(f"start_user_nicks called for user={user_id} (no-op — frontend re-triggers)")

    async def _loop(self, nick_live_id: int, session_id: int, cookies: str) -> None:
        try:
            while True:
                db = SessionLocal()
                try:
                    svc = SettingsService(db)
                    templates = svc.get_auto_post_templates_for_nick(nick_live_id)
                finally:
                    db.close()

                if not templates:
                    logger.warning(f"No templates for nick={nick_live_id}, stopping")
                    break

                idx = self._template_index.get(nick_live_id, 0) % len(templates)
                tmpl = templates[idx]
                self._template_index[nick_live_id] = idx + 1

                interval = random.uniform(tmpl.min_interval_seconds, tmpl.max_interval_seconds)
                logger.debug(f"Auto-post nick={nick_live_id}: sleeping {interval:.0f}s")
                await asyncio.sleep(interval)

                channel_results = await self._send(
                    nick_live_id, session_id, cookies, tmpl.content
                )

                if not channel_results:
                    reply_log_writer.enqueue({
                        "nick_live_id": nick_live_id,
                        "session_id": session_id,
                        "guest_name": "[auto-post]",
                        "guest_id": 0,
                        "comment_text": "",
                        "reply_text": tmpl.content,
                        "reply_type": "autopost",
                        "outcome": "failed",
                        "error": "no_channel_enabled",
                        "status_code": None,
                        "latency_ms": 0,
                        "llm_latency_ms": 0,
                        "cached_hit": False,
                    })
                else:
                    for channel, result in channel_results:
                        reply_log_writer.enqueue({
                            "nick_live_id": nick_live_id,
                            "session_id": session_id,
                            "guest_name": "[auto-post]",
                            "guest_id": 0,
                            "comment_text": "",
                            "reply_text": tmpl.content,
                            "reply_type": f"autopost_{channel}",
                            "outcome": "success" if result.get("success") else "failed",
                            "error": result.get("error"),
                            "status_code": result.get("status_code"),
                            "latency_ms": 0,
                            "llm_latency_ms": 0,
                            "cached_hit": False,
                        })

        except asyncio.CancelledError:
            logger.info(f"Auto-post loop cancelled for nick={nick_live_id}")
        except Exception:
            logger.exception(f"Auto-post loop crashed for nick={nick_live_id}")
        finally:
            self._tasks.pop(nick_live_id, None)
            self._template_index.pop(nick_live_id, None)

    async def _send(
        self, nick_live_id: int, session_id: int, cookies: str, content: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Send to each enabled channel independently. Returns list of (channel, result)."""
        from app.services.nick_cache import nick_cache
        settings = await nick_cache.get_settings(nick_live_id, SessionLocal)

        results: list[tuple[str, dict[str, Any]]] = []

        if settings.auto_post_to_host and self._moderator.has_host_config(nick_live_id):
            body = self._moderator.generate_host_post_body(nick_live_id, content)
            if body:
                r = await self._moderator.send_host_message(
                    nick_live_id, session_id, body, cookies
                )
                results.append(("host", r))

        if settings.auto_post_to_moderator and self._moderator.has_config(nick_live_id):
            body = self._moderator.generate_moderator_post_body(nick_live_id, content)
            if body:
                r = await self._moderator.send_moderator_message(
                    nick_live_id, session_id, body
                )
                results.append(("moderator", r))

        return results
