"""Per-session coordinated seeding scheduler.

One asyncio task per SeedingLogSession (auto mode). Each tick:
 1) sleep random [min, max]
 2) load enabled templates (user-scoped); if empty → stop
 3) load clones from the frozen config; drop clones blocked by 10s floor
 4) if none eligible → write a 'rate_limited' log (against the first clone by id)
 5) else pick random clone + template and call seeding_sender.send(mode='auto')
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from app.database import SessionLocal
from app.models.seeding import (
    SeedingClone,
    SeedingCommentTemplate,
    SeedingLog,
    SeedingLogSession,
)
from app.services.seeding_sender import CLONE_FLOOR_SEC, seeding_sender

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeedingRunConfig:
    log_session_id: int
    user_id: int
    nick_live_id: int
    shopee_session_id: int
    clone_ids: tuple[int, ...]
    min_interval_sec: int
    max_interval_sec: int


class SeedingScheduler:
    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}
        self._configs: dict[int, SeedingRunConfig] = {}

    def is_running(self, log_session_id: int) -> bool:
        t = self._tasks.get(log_session_id)
        return t is not None and not t.done()

    def running_configs(self, user_id: int) -> list[SeedingRunConfig]:
        return [c for c in self._configs.values()
                if c.user_id == user_id and self.is_running(c.log_session_id)]

    def start(self, cfg: SeedingRunConfig) -> None:
        if self.is_running(cfg.log_session_id):
            raise ValueError(f"log_session_id={cfg.log_session_id} already running")
        self._configs[cfg.log_session_id] = cfg
        self._tasks[cfg.log_session_id] = asyncio.create_task(self._loop(cfg))
        logger.info(f"seeding scheduler start log_session_id={cfg.log_session_id}")

    async def stop(self, log_session_id: int) -> bool:
        task = self._tasks.pop(log_session_id, None)
        self._configs.pop(log_session_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._mark_stopped(log_session_id)
        logger.info(f"seeding scheduler stop log_session_id={log_session_id}")
        return True

    def stop_all(self) -> None:
        for sid in list(self._tasks):
            task = self._tasks.pop(sid)
            self._configs.pop(sid, None)
            if not task.done():
                task.cancel()

    async def _loop(self, cfg: SeedingRunConfig) -> None:
        try:
            while True:
                cont = await self._iteration(cfg)
                if cont is False:
                    break
        except asyncio.CancelledError:
            logger.info(f"seeding loop cancelled sid={cfg.log_session_id}")
            raise
        except Exception:
            logger.exception(f"seeding loop crashed sid={cfg.log_session_id}")
        finally:
            self._tasks.pop(cfg.log_session_id, None)
            self._configs.pop(cfg.log_session_id, None)
            self._mark_stopped(cfg.log_session_id)

    async def _iteration(self, cfg: SeedingRunConfig) -> bool:
        await asyncio.sleep(random.uniform(cfg.min_interval_sec, cfg.max_interval_sec))

        templates = self._load_templates(cfg.user_id)
        if not templates:
            logger.warning(f"no enabled templates for user={cfg.user_id}, stopping")
            return False

        clones = self._load_clones(list(cfg.clone_ids))
        eligible = [c for c in clones if self._is_eligible(c.last_sent_at)]

        if not eligible:
            first_id = sorted(cfg.clone_ids)[0]
            self._write_rate_limited_log(
                log_session_id=cfg.log_session_id,
                clone_id=first_id,
                content="",
            )
            return True

        clone = random.choice(eligible)
        template = random.choice(templates)

        try:
            await seeding_sender.send(
                clone_id=clone.id,
                nick_live_id=cfg.nick_live_id,
                shopee_session_id=cfg.shopee_session_id,
                content=template.content,
                template_id=template.id,
                mode="auto",
                log_session_id=cfg.log_session_id,
            )
        except Exception:
            logger.exception("seeding_sender.send raised in auto mode")

        return True

    def _is_eligible(self, last_sent_at: datetime | None) -> bool:
        if last_sent_at is None:
            return True
        if last_sent_at.tzinfo is None:
            last_sent_at = last_sent_at.replace(tzinfo=timezone.utc)
        delta = (datetime.now(timezone.utc) - last_sent_at).total_seconds()
        return delta >= CLONE_FLOOR_SEC

    def _load_templates(self, user_id: int) -> list[SeedingCommentTemplate]:
        with SessionLocal() as db:
            return (db.query(SeedingCommentTemplate)
                    .filter(SeedingCommentTemplate.user_id == user_id,
                            SeedingCommentTemplate.enabled.is_(True))
                    .all())

    def _load_clones(self, ids: list[int]) -> list[SeedingClone]:
        if not ids:
            return []
        with SessionLocal() as db:
            return db.query(SeedingClone).filter(SeedingClone.id.in_(ids)).all()

    def _write_rate_limited_log(
        self, *, log_session_id: int, clone_id: int, content: str,
    ) -> None:
        with SessionLocal() as db:
            db.add(SeedingLog(
                seeding_log_session_id=log_session_id,
                clone_id=clone_id,
                template_id=None,
                content=content,
                status="rate_limited",
                error="no eligible clones",
            ))
            db.commit()

    def _mark_stopped(self, log_session_id: int) -> None:
        with SessionLocal() as db:
            row = db.query(SeedingLogSession).filter(
                SeedingLogSession.id == log_session_id
            ).first()
            if row is not None and row.stopped_at is None:
                row.stopped_at = datetime.now(timezone.utc)
                db.commit()


seeding_scheduler = SeedingScheduler()
