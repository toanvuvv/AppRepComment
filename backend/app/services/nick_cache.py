"""TTL-based runtime cache for per-nick settings and products.

Avoids opening a SQLAlchemy session on every poll iteration by caching
the fields consumed by the reply pipeline. Caches are invalidated either
by TTL expiry or explicitly via `invalidate*()` when settings are updated.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, NamedTuple

from app.config import NICK_CACHE_TTL_SEC

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NickSettingsSnapshot:
    """Immutable snapshot of the per-nick settings needed by the reply pipeline."""

    reply_mode: str  # "none" | "knowledge" | "ai" | "template"
    reply_to_host: bool
    reply_to_moderator: bool
    auto_post_enabled: bool
    auto_post_to_host: bool
    auto_post_to_moderator: bool
    host_config: dict | None
    moderator_config: dict | None
    openai_api_key: str | None
    openai_model: str | None
    system_prompt: str
    knowledge_model: str | None
    knowledge_system_prompt: str
    banned_words: tuple[str, ...]


class ProductSnapshot(NamedTuple):
    """Detached product row — mirrors KnowledgeProduct fields used at reply time."""

    product_order: int
    name: str
    price_min: int | None
    price_max: int | None
    discount_pct: int | None
    in_stock: bool
    stock_qty: int | None
    sold: int | None
    rating: float | None
    rating_count: int | None
    voucher_info: str | None
    promotion_info: str | None
    keywords: str | None  # raw JSON string; parsed index lives alongside


class _SettingsEntry(NamedTuple):
    value: NickSettingsSnapshot
    expires_at: float


class _ProductsEntry(NamedTuple):
    products: tuple[ProductSnapshot, ...]
    keyword_index: dict[int, list[str]]
    expires_at: float


DbFactory = Callable[[], Any]


class NickRuntimeCache:
    """Async cache keyed by nick_live_id with TTL + per-key locking."""

    def __init__(self, ttl_sec: float = NICK_CACHE_TTL_SEC) -> None:
        self._ttl: float = ttl_sec
        self._settings: dict[int, _SettingsEntry] = {}
        self._products: dict[int, _ProductsEntry] = {}
        self._settings_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._products_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    # --- public API -----------------------------------------------------

    async def get_settings(
        self, nick_live_id: int, db_factory: DbFactory
    ) -> NickSettingsSnapshot:
        entry = self._settings.get(nick_live_id)
        if entry is not None and entry.expires_at > time.monotonic():
            return entry.value

        lock = self._settings_locks[nick_live_id]
        async with lock:
            # Double-check after waiting for the lock — another coroutine
            # may have already refreshed the cache.
            entry = self._settings.get(nick_live_id)
            if entry is not None and entry.expires_at > time.monotonic():
                return entry.value

            snapshot = await asyncio.to_thread(
                self._load_settings_sync, nick_live_id, db_factory
            )
            self._settings[nick_live_id] = _SettingsEntry(
                value=snapshot,
                expires_at=time.monotonic() + self._ttl,
            )
            return snapshot

    async def get_products(
        self, nick_live_id: int, db_factory: DbFactory
    ) -> tuple[list[ProductSnapshot], dict[int, list[str]]]:
        entry = self._products.get(nick_live_id)
        if entry is not None and entry.expires_at > time.monotonic():
            return list(entry.products), dict(entry.keyword_index)

        lock = self._products_locks[nick_live_id]
        async with lock:
            entry = self._products.get(nick_live_id)
            if entry is not None and entry.expires_at > time.monotonic():
                return list(entry.products), dict(entry.keyword_index)

            products, keyword_index = await asyncio.to_thread(
                self._load_products_sync, nick_live_id, db_factory
            )
            self._products[nick_live_id] = _ProductsEntry(
                products=tuple(products),
                keyword_index=keyword_index,
                expires_at=time.monotonic() + self._ttl,
            )
            return list(products), dict(keyword_index)

    def invalidate(self, nick_live_id: int) -> None:
        self.invalidate_settings(nick_live_id)
        self.invalidate_products(nick_live_id)

    def invalidate_settings(self, nick_live_id: int) -> None:
        self._settings.pop(nick_live_id, None)

    def invalidate_products(self, nick_live_id: int) -> None:
        self._products.pop(nick_live_id, None)

    # --- internal loaders (run on worker thread) ------------------------

    @staticmethod
    def _load_settings_sync(
        nick_live_id: int, db_factory: DbFactory
    ) -> NickSettingsSnapshot:
        # Local imports to avoid import cycles at module load time.
        from app.services.settings_service import SettingsService

        db = db_factory()
        try:
            svc = SettingsService(db)
            row = svc.get_or_create_nick_settings(nick_live_id)

            host_config_dict: dict | None = None
            if row.host_config:
                try:
                    host_config_dict = json.loads(row.host_config)
                except (json.JSONDecodeError, TypeError):
                    host_config_dict = None

            moderator_config_dict: dict | None = None
            if row.moderator_config:
                try:
                    moderator_config_dict = json.loads(row.moderator_config)
                except (json.JSONDecodeError, TypeError):
                    moderator_config_dict = None

            snapshot = NickSettingsSnapshot(
                reply_mode=str(getattr(row, "reply_mode", "none") or "none"),
                reply_to_host=bool(getattr(row, "reply_to_host", False)),
                reply_to_moderator=bool(getattr(row, "reply_to_moderator", False)),
                auto_post_enabled=bool(row.auto_post_enabled),
                auto_post_to_host=bool(getattr(row, "auto_post_to_host", False)),
                auto_post_to_moderator=bool(getattr(row, "auto_post_to_moderator", False)),
                host_config=host_config_dict,
                moderator_config=moderator_config_dict,
                openai_api_key=svc.get_openai_api_key(),
                openai_model=svc.get_setting("openai_model"),
                system_prompt=svc.get_system_prompt() or "",
                knowledge_model=svc.get_knowledge_model(),
                knowledge_system_prompt=svc.get_knowledge_system_prompt() or "",
                banned_words=tuple(svc.get_banned_words()),
            )
            return snapshot
        finally:
            try:
                db.close()
            except Exception:
                logger.debug("db.close() failed in settings loader", exc_info=True)

    @staticmethod
    def _load_products_sync(
        nick_live_id: int, db_factory: DbFactory
    ) -> tuple[list[ProductSnapshot], dict[int, list[str]]]:
        from app.services.knowledge_product_service import KnowledgeProductService

        db = db_factory()
        try:
            kp_svc = KnowledgeProductService(db)
            rows = kp_svc.get_products(nick_live_id)

            products: list[ProductSnapshot] = []
            keyword_index: dict[int, list[str]] = {}

            for p in rows:
                snap = ProductSnapshot(
                    product_order=p.product_order,
                    name=p.name,
                    price_min=p.price_min,
                    price_max=p.price_max,
                    discount_pct=p.discount_pct,
                    in_stock=bool(p.in_stock),
                    stock_qty=p.stock_qty,
                    sold=p.sold,
                    rating=p.rating,
                    rating_count=p.rating_count,
                    voucher_info=p.voucher_info,
                    promotion_info=p.promotion_info,
                    keywords=p.keywords,
                )
                products.append(snap)

                try:
                    keyword_index[p.product_order] = (
                        json.loads(p.keywords) if p.keywords else []
                    )
                except (json.JSONDecodeError, TypeError):
                    keyword_index[p.product_order] = []

            return products, keyword_index
        finally:
            try:
                db.close()
            except Exception:
                logger.debug("db.close() failed in products loader", exc_info=True)


# Singleton — callers pass SessionLocal as db_factory.
nick_cache: NickRuntimeCache = NickRuntimeCache()
