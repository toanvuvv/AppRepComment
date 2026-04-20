"""Auto-pin worker: on a random min/max interval pins a random in-stock product."""

import asyncio
import logging
import random
from typing import Any

from app.database import SessionLocal

logger = logging.getLogger(__name__)

# Capture a reference to the real asyncio.sleep at module-import time so that
# unit tests that monkeypatch `asyncio.sleep` on this module do not break the
# event-loop's own scheduling (the loop needs at least one genuine yield per
# iteration to stay cooperative even when the interval sleep is replaced with a
# synchronous stub).
_real_sleep = asyncio.sleep

# Module-level alias so tests can monkeypatch sleep without affecting
# asyncio.sleep globally.
_sleep = asyncio.sleep


class AutoPinner:
    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}

    def is_running(self, nick_live_id: int) -> bool:
        task = self._tasks.get(nick_live_id)
        return task is not None and not task.done()

    # --- Data loaders (overridable in tests via patch.object) ---

    def _load_settings(self, nick_live_id: int):
        """Return (NickLiveSetting, user_id). Raises if nick not found."""
        from app.models.nick_live import NickLive
        from app.services.settings_service import SettingsService
        with SessionLocal() as db:
            nick = db.query(NickLive).filter(NickLive.id == nick_live_id).first()
            if not nick:
                raise ValueError(f"Nick not found: {nick_live_id}")
            svc = SettingsService(db, user_id=nick.user_id)
            row = svc.get_or_create_nick_settings(nick_live_id)
            db.expunge(row)
            return row, nick.user_id

    def _load_api_key(self, user_id: int) -> str | None:
        from app.services.settings_service import SettingsService
        with SessionLocal() as db:
            svc = SettingsService(db, user_id=user_id)
            return svc.get_setting("relive_api_key")

    def _count_in_stock(self, nick_live_id: int) -> int:
        from app.models.knowledge_product import KnowledgeProduct
        with SessionLocal() as db:
            return (
                db.query(KnowledgeProduct)
                .filter(
                    KnowledgeProduct.nick_live_id == nick_live_id,
                    KnowledgeProduct.in_stock.is_(True),
                )
                .count()
            )

    def _load_in_stock_products(self, nick_live_id: int) -> list:
        from app.models.knowledge_product import KnowledgeProduct
        with SessionLocal() as db:
            rows = (
                db.query(KnowledgeProduct)
                .filter(
                    KnowledgeProduct.nick_live_id == nick_live_id,
                    KnowledgeProduct.in_stock.is_(True),
                )
                .all()
            )
            return [(r.item_id, r.shop_id) for r in rows]

    def _user_nick_ids(self, user_id: int) -> list[int]:
        from app.models.nick_live import NickLive
        with SessionLocal() as db:
            return [nid for (nid,) in db.query(NickLive.id)
                    .filter(NickLive.user_id == user_id).all()]

    # --- Lifecycle ---

    async def start(
        self, nick_live_id: int, session_id: int, cookies: str,
    ) -> dict[str, Any]:
        if self.is_running(nick_live_id):
            return {"status": "already_running"}

        try:
            settings, user_id = self._load_settings(nick_live_id)
        except ValueError as exc:
            return {"error": str(exc)}

        if not settings.auto_pin_enabled:
            return {"error": "Auto Pin chưa được bật"}

        if self._count_in_stock(nick_live_id) == 0:
            return {"error": "Chưa có sản phẩm còn hàng để pin"}

        api_key = self._load_api_key(user_id)
        if not api_key:
            return {"error": "Chưa cấu hình Relive API key"}

        task = asyncio.create_task(self._loop(nick_live_id, session_id, cookies))
        self._tasks[nick_live_id] = task
        logger.info(f"Auto-pin started for nick={nick_live_id}")
        return {"status": "started"}

    async def stop(self, nick_live_id: int) -> dict[str, Any]:
        task = self._tasks.pop(nick_live_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info(f"Auto-pin stopped for nick={nick_live_id}")
            return {"status": "stopped"}
        return {"status": "not_running"}

    def stop_all(self) -> None:
        for nick_id in list(self._tasks):
            task = self._tasks.pop(nick_id)
            if not task.done():
                task.cancel()

    def stop_user_nicks(self, user_id: int) -> None:
        for nid in self._user_nick_ids(user_id):
            task = self._tasks.pop(nid, None)
            if task and not task.done():
                task.cancel()
                logger.info(f"Auto-pin stopped (lock) for nick={nid} user={user_id}")

    def start_user_nicks(self, user_id: int) -> None:
        """No-op — frontend re-triggers start when needed (parity with AutoPoster)."""
        logger.info(f"start_user_nicks(pin) called for user={user_id} (no-op)")

    # --- Loop body ---

    async def _loop(self, nick_live_id: int, session_id: int, cookies: str) -> None:
        import app.services.relive_service as _relive_svc
        try:
            while True:
                # Guaranteed cooperative yield so the event loop stays responsive
                # even when asyncio.sleep is replaced by a synchronous stub in tests.
                await _real_sleep(0)

                try:
                    settings, user_id = self._load_settings(nick_live_id)
                except Exception:
                    logger.exception(f"Auto-pin nick={nick_live_id}: settings load failed")
                    await _sleep(60)
                    continue

                lo = max(1, int(settings.pin_min_interval_minutes)) * 60
                hi = max(lo, int(settings.pin_max_interval_minutes) * 60)
                interval = random.uniform(lo, hi)
                logger.debug(f"Auto-pin nick={nick_live_id}: sleeping {interval:.0f}s")
                await _sleep(interval)

                products = self._load_in_stock_products(nick_live_id)
                if not products:
                    logger.warning(
                        f"Auto-pin nick={nick_live_id}: no in_stock products, retry next cycle"
                    )
                    continue

                item_id, shop_id = random.choice(products)
                api_key = self._load_api_key(user_id)
                if not api_key:
                    logger.warning(f"Auto-pin nick={nick_live_id}: missing relive_api_key")
                    continue

                proxy = getattr(settings, "host_proxy", None)
                try:
                    await _relive_svc.pin_livestream_item(
                        api_key=api_key,
                        cookies=cookies,
                        session_id=session_id,
                        item_id=item_id,
                        shop_id=shop_id,
                        proxy=proxy,
                    )
                    logger.info(
                        f"Auto-pin nick={nick_live_id} item={item_id} shop={shop_id}"
                    )
                except Exception:
                    logger.exception(f"Auto-pin failed nick={nick_live_id}")
                    # swallow — continue loop

        except asyncio.CancelledError:
            logger.info(f"Auto-pin loop cancelled for nick={nick_live_id}")
        except Exception:
            logger.exception(f"Auto-pin loop crashed for nick={nick_live_id}")
        finally:
            self._tasks.pop(nick_live_id, None)
