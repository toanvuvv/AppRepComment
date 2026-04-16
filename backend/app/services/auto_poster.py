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

        has_host = self._moderator.has_host_config(nick_live_id)
        has_mod = self._moderator.has_config(nick_live_id)
        if not has_host and not has_mod:
            return {"error": "No host or moderator credentials configured"}

        db = SessionLocal()
        try:
            svc = SettingsService(db)
            templates = svc.get_auto_post_templates_for_nick(nick_live_id)
        finally:
            db.close()

        if not templates:
            return {"error": "No auto-post templates for this nick"}

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

                result = await self._send(nick_live_id, session_id, cookies, tmpl.content)

                reply_log_writer.enqueue({
                    "nick_live_id": nick_live_id,
                    "session_id": session_id,
                    "guest_name": "[auto-post]",
                    "guest_id": 0,
                    "comment_text": "",
                    "reply_text": tmpl.content,
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
    ) -> dict[str, Any]:
        if self._moderator.has_host_config(nick_live_id):
            body = self._moderator.generate_host_post_body(nick_live_id, content, use_host=True)
            if body:
                return await self._moderator.send_host_message(nick_live_id, session_id, body, cookies)

        if self._moderator.has_config(nick_live_id):
            body = self._moderator.generate_host_post_body(nick_live_id, content, use_host=False)
            if body:
                return await self._moderator.send_reply_raw(nick_live_id, session_id, body)

        return {"success": False, "error": "no_credentials"}
