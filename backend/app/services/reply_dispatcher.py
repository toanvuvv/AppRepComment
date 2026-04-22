"""Producer-consumer reply dispatcher.

Owns a per-nick asyncio.Queue and a small pool of worker tasks.  A global
semaphore bounds total simultaneous LLM calls across all nicks.

Each reply attempt is observed: per-nick circuit breaker gates LLM calls,
a short-TTL cache deduplicates identical comments, and every outcome
(success / failed / dropped / circuit_open / no_config) is logged to the
``reply_logs`` table via the batched ``reply_log_writer``.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time

from app.config import REPLY_CONCURRENCY, REPLY_QUEUE_MAX, REPLY_WORKER_COUNT
from app.services.circuit_breaker import circuit_registry
from app.services.reply_cache import reply_cache
from app.services.reply_log_writer import reply_log_writer

logger = logging.getLogger(__name__)


class ReplyDispatcher:
    """Per-nick queue + shared worker pool for LLM replies."""

    def __init__(
        self,
        worker_count: int = REPLY_WORKER_COUNT,
        max_concurrency: int = REPLY_CONCURRENCY,
        max_queue: int = REPLY_QUEUE_MAX,
    ) -> None:
        self._worker_count: int = worker_count
        self._max_queue: int = max_queue

        # Global LLM concurrency limiter shared across all workers/nicks.
        self._llm_semaphore: asyncio.Semaphore = asyncio.Semaphore(max_concurrency)

        # Per-nick state.
        self._queues: dict[int, asyncio.Queue] = {}
        self._workers: dict[int, list[asyncio.Task]] = {}
        self._sessions: dict[int, int] = {}
        self._cookies: dict[int, str] = {}

    # --- lifecycle -------------------------------------------------------

    def start(self, nick_live_id: int, session_id: int, cookies: str) -> None:
        """Idempotently start workers for a nick."""
        if self.is_running(nick_live_id):
            # Update session/cookies in case they rotated.
            self._sessions[nick_live_id] = session_id
            self._cookies[nick_live_id] = cookies
            return

        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        self._queues[nick_live_id] = queue
        self._sessions[nick_live_id] = session_id
        self._cookies[nick_live_id] = cookies

        tasks = [
            asyncio.create_task(
                self._worker(nick_live_id, queue),
                name=f"reply-worker-{nick_live_id}-{i}",
            )
            for i in range(self._worker_count)
        ]
        self._workers[nick_live_id] = tasks
        logger.info(
            f"Started {self._worker_count} reply worker(s) for nick_live={nick_live_id}"
        )

    def stop(self, nick_live_id: int) -> None:
        """Cancel workers and drop queue for the given nick."""
        tasks = self._workers.pop(nick_live_id, [])
        for t in tasks:
            if not t.done():
                t.cancel()

        self._queues.pop(nick_live_id, None)
        self._sessions.pop(nick_live_id, None)
        self._cookies.pop(nick_live_id, None)
        logger.info(f"Stopped reply workers for nick_live={nick_live_id}")

    def is_running(self, nick_live_id: int) -> bool:
        tasks = self._workers.get(nick_live_id)
        if not tasks:
            return False
        return any(not t.done() for t in tasks)

    def queue_depth(self, nick_live_id: int) -> int:
        q = self._queues.get(nick_live_id)
        return q.qsize() if q is not None else 0

    # --- producer --------------------------------------------------------

    async def enqueue(self, nick_live_id: int, comment: dict) -> bool:
        """Enqueue a comment for reply processing.

        Returns False (and logs) if the queue is full or workers are not
        running. Never raises QueueFull to callers.
        """
        queue = self._queues.get(nick_live_id)
        if queue is None:
            logger.warning(
                f"enqueue: no queue for nick_live={nick_live_id} (not started?)"
            )
            return False

        try:
            queue.put_nowait(comment)
            return True
        except asyncio.QueueFull:
            logger.warning(
                f"Reply queue full for nick_live={nick_live_id} "
                f"(max={self._max_queue}); dropping comment"
            )
            return False

    # --- consumer --------------------------------------------------------

    async def _worker(self, nick_live_id: int, q: asyncio.Queue) -> None:
        """Long-running consumer; one per worker slot per nick."""
        logger.debug(f"Reply worker started for nick_live={nick_live_id}")
        try:
            while True:
                comment = await q.get()
                try:
                    session_id = self._sessions.get(nick_live_id)
                    cookies = self._cookies.get(nick_live_id, "")
                    if session_id is None:
                        logger.warning(
                            f"Worker: session missing for nick_live={nick_live_id}; "
                            f"dropping comment"
                        )
                        continue

                    async with self._llm_semaphore:
                        await self._handle(
                            nick_live_id, session_id, cookies, comment
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.error(
                        f"Reply handler failed for nick_live={nick_live_id}",
                        exc_info=True,
                    )
                finally:
                    q.task_done()
        except asyncio.CancelledError:
            logger.debug(f"Reply worker cancelled for nick_live={nick_live_id}")
            raise

    async def _handle(
        self,
        nick_live_id: int,
        session_id: int,
        cookies: str,
        comment: dict,
    ) -> None:
        """Process a single comment: circuit-gate, cache, LLM, send, log.

        Uses nick_cache snapshots instead of opening a fresh DB session.
        Every terminal outcome is written to the reply_logs table.
        """
        # Local imports to avoid circular imports at module load time.
        from app.database import SessionLocal
        from app.services.ai_reply_service import generate_reply
        from app.services.knowledge_reply_service import (
            extract_product_reference,
            filter_banned_words,
            generate_knowledge_reply,
        )
        from app.services.live_moderator import moderator
        from app.services.nick_cache import nick_cache
        from app.services.settings_service import SettingsService

        t0 = time.monotonic()

        content = comment.get("content") or comment.get("text") or ""
        if not content:
            # Empty/noise — skip entirely without logging.
            return

        username = (
            comment.get("username")
            or comment.get("userName")
            or comment.get("nick_name")
            or comment.get("nickname")
            or "Unknown"
        )
        user_id = comment.get("streamerId") or comment.get("userId") or 0

        base_log: dict = {
            "nick_live_id": nick_live_id,
            "session_id": session_id,
            "guest_name": username,
            "guest_id": str(user_id) if user_id is not None else None,
            "comment_text": content,
        }

        settings = await nick_cache.get_settings(nick_live_id, SessionLocal)

        # --- Self-reply guard (defense-in-depth) ---
        # The scanner already filters self-posts before enqueue, but we
        # re-check here so callers that bypass the scanner (e.g. future
        # queue injectors) are also safe. See services.self_post_filter.
        from app.services.self_post_filter import is_self_post
        if is_self_post(comment, settings):
            logger.debug(
                "Dispatcher skipping self-post nick=%s uid=%s",
                nick_live_id,
                user_id,
            )
            return

        # --- Skip if nothing to do ---
        if settings.reply_mode == "none":
            return
        if not settings.reply_to_host and not settings.reply_to_moderator:
            return

        mode = settings.reply_mode
        has_mod = settings.reply_to_moderator and moderator.has_config(nick_live_id)
        has_host = settings.reply_to_host and moderator.has_host_config(nick_live_id)

        if not has_mod and not has_host:
            logger.warning(
                f"Reply path: enabled channel(s) have no credentials for "
                f"nick={nick_live_id}"
            )
            await reply_log_writer.log({
                **base_log,
                "reply_text": None,
                "reply_type": None,
                "outcome": "no_config",
                "error": "no_mod_or_host_config",
                "latency_ms": int((time.monotonic() - t0) * 1000),
            })
            return

        # --- Generate reply text based on mode ---
        reply_text: str | None = None
        product_order: int | None = None
        product_context: dict | None = None
        system_prompt: str | None = None
        model: str | None = None
        llm_latency_ms: int = 0
        cached_hit: bool = False

        if mode in ("knowledge", "ai"):
            if not settings.openai_api_key:
                logger.warning("openai_api_key missing")
                await reply_log_writer.log({
                    **base_log,
                    "reply_text": None,
                    "reply_type": mode,
                    "outcome": "failed",
                    "error": "openai_api_key missing",
                    "latency_ms": int((time.monotonic() - t0) * 1000),
                })
                return

            if mode == "knowledge":
                products, keyword_index = await nick_cache.get_products(
                    nick_live_id, SessionLocal
                )
                if not products:
                    logger.warning(
                        f"Knowledge mode enabled but no products for "
                        f"nick={nick_live_id}"
                    )
                    await reply_log_writer.log({
                        **base_log,
                        "reply_text": None,
                        "reply_type": mode,
                        "outcome": "failed",
                        "error": "knowledge_enabled_but_no_products",
                        "latency_ms": int((time.monotonic() - t0) * 1000),
                    })
                    return

                model = (
                    settings.knowledge_model
                    or settings.openai_model
                    or "gpt-4o"
                )
                product_order = extract_product_reference(content, keyword_index)
                if product_order is not None:
                    prod = next(
                        (p for p in products if p.product_order == product_order),
                        None,
                    )
                    if prod:
                        product_context = {
                            "product_order": prod.product_order,
                            "name": prod.name,
                            "price_min": prod.price_min,
                            "price_max": prod.price_max,
                            "discount_pct": prod.discount_pct,
                            "in_stock": prod.in_stock,
                            "stock_qty": prod.stock_qty,
                            "sold": prod.sold,
                            "rating": prod.rating,
                            "rating_count": prod.rating_count,
                            "voucher_info": prod.voucher_info,
                            "promotion_info": prod.promotion_info,
                        }
                system_prompt = settings.knowledge_system_prompt or None
            else:  # ai
                model = settings.openai_model or "gpt-4o"
                system_prompt = settings.system_prompt or "Bạn là nhân viên CSKH."

            # --- circuit breaker ---
            circuit = circuit_registry.for_nick(nick_live_id)
            if not circuit.can_attempt():
                logger.warning(f"Circuit open for nick={nick_live_id}, skipping LLM")
                await reply_log_writer.log({
                    **base_log,
                    "reply_text": None,
                    "reply_type": mode,
                    "outcome": "circuit_open",
                    "error": f"Circuit breaker OPEN for nick {nick_live_id}",
                    "product_order": product_order if mode == "knowledge" else None,
                    "latency_ms": int((time.monotonic() - t0) * 1000),
                })
                return

            # --- cache + LLM ---
            cached = reply_cache.get(nick_live_id, content)
            if cached is not None:
                reply_text = cached
                cached_hit = True
            else:
                t_llm = time.monotonic()
                try:
                    if mode == "knowledge":
                        reply_text = await generate_knowledge_reply(
                            api_key=settings.openai_api_key,
                            model=model,
                            comment_text=content,
                            guest_name=username,
                            product_context=product_context,
                            system_prompt_override=system_prompt,
                        )
                    else:
                        reply_text = await generate_reply(
                            api_key=settings.openai_api_key,
                            model=model,
                            system_prompt=system_prompt,
                            comment_text=content,
                            guest_name=username,
                        )
                except Exception as e:
                    circuit.record_failure()
                    llm_latency_ms = int((time.monotonic() - t_llm) * 1000)
                    logger.exception(f"LLM error for nick={nick_live_id}")
                    await reply_log_writer.log({
                        **base_log,
                        "reply_text": None,
                        "reply_type": mode,
                        "outcome": "failed",
                        "error": f"llm_error: {e}"[:500],
                        "product_order": product_order if mode == "knowledge" else None,
                        "latency_ms": int((time.monotonic() - t0) * 1000),
                        "llm_latency_ms": llm_latency_ms,
                        "cached_hit": False,
                    })
                    return
                llm_latency_ms = int((time.monotonic() - t_llm) * 1000)

                if reply_text:
                    reply_text = filter_banned_words(
                        reply_text, list(settings.banned_words)
                    )
                    reply_cache.put(nick_live_id, content, reply_text)

            if not reply_text:
                circuit.record_failure()
                await reply_log_writer.log({
                    **base_log,
                    "reply_text": None,
                    "reply_type": mode,
                    "outcome": "failed",
                    "error": "empty_llm_response",
                    "product_order": product_order if mode == "knowledge" else None,
                    "latency_ms": int((time.monotonic() - t0) * 1000),
                    "llm_latency_ms": llm_latency_ms,
                    "cached_hit": cached_hit,
                })
                return

        elif mode == "template":
            # Pick a random per-nick reply template.
            db = SessionLocal()
            try:
                svc = SettingsService(db)
                templates = svc.get_reply_templates_for_nick(nick_live_id)
            finally:
                db.close()

            if not templates:
                logger.warning(f"Template mode but no templates for nick={nick_live_id}")
                await reply_log_writer.log({
                    **base_log,
                    "reply_text": None,
                    "reply_type": mode,
                    "outcome": "failed",
                    "error": "no_templates",
                    "latency_ms": int((time.monotonic() - t0) * 1000),
                })
                return
            reply_text = random.choice(templates).content
            if reply_text:
                reply_text = filter_banned_words(
                    reply_text, list(settings.banned_words)
                )
        else:
            # Unknown mode — safety net.
            return

        if not reply_text:
            return

        # --- Send to enabled channels ---
        circuit = circuit_registry.for_nick(nick_live_id)

        if has_mod:
            mod_body = moderator.generate_moderator_reply_body(
                nick_live_id, username, int(user_id) if user_id else 0, reply_text
            )
            if mod_body:
                result = await moderator.send_moderator_message(
                    nick_live_id, session_id, mod_body
                )
                success = bool(result.get("success"))
                if mode in ("knowledge", "ai"):
                    if success:
                        circuit.record_success()
                    else:
                        circuit.record_failure()
                logger.info(
                    f"[mod_{mode}] {username}: {reply_text[:50]}... -> {success}"
                )
                await reply_log_writer.log({
                    **base_log,
                    "reply_text": reply_text,
                    "reply_type": f"mod_{mode}",
                    "outcome": "success" if success else "failed",
                    "status_code": result.get("status_code"),
                    "error": None if success else result.get("error"),
                    "product_order": product_order if mode == "knowledge" else None,
                    "latency_ms": int((time.monotonic() - t0) * 1000),
                    "llm_latency_ms": llm_latency_ms,
                    "cached_hit": cached_hit,
                })

        if has_host:
            host_body = moderator.generate_host_reply_body(
                nick_live_id, username, str(user_id), reply_text
            )
            if host_body:
                host_result = await moderator.send_host_message(
                    nick_live_id, session_id, host_body, cookies
                )
                host_success = bool(host_result.get("success"))
                logger.info(
                    f"[host_{mode}] {username}: "
                    f"{reply_text[:50]}... -> {host_success}"
                )
                await reply_log_writer.log({
                    **base_log,
                    "reply_text": reply_text,
                    "reply_type": f"host_{mode}",
                    "outcome": "success" if host_success else "failed",
                    "error": host_result.get("error") if not host_success else None,
                    "status_code": host_result.get("status_code"),
                    "product_order": product_order if mode == "knowledge" else None,
                    "latency_ms": int((time.monotonic() - t0) * 1000),
                    "llm_latency_ms": llm_latency_ms,
                    "cached_hit": cached_hit,
                })


# Singleton used by the scanner and API layer.
dispatcher: ReplyDispatcher = ReplyDispatcher()
