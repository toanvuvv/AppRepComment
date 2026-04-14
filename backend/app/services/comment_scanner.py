import asyncio
import logging
import time
from collections import defaultdict

from app.database import SessionLocal
from app.services.shopee_api import get_comments

logger = logging.getLogger(__name__)


class CommentScanner:
    """Manages background comment polling tasks for multiple nick lives"""

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}  # nick_live_id -> Task
        self._comments: dict[int, list] = defaultdict(list)  # nick_live_id -> comments
        self._seen_ids: dict[int, set] = defaultdict(set)  # nick_live_id -> seen IDs
        self._session_ids: dict[int, int] = {}  # nick_live_id -> session_id
        self._new_comments: dict[int, asyncio.Queue] = {}  # for SSE streaming

    def is_scanning(self, nick_live_id: int) -> bool:
        return nick_live_id in self._tasks and not self._tasks[nick_live_id].done()

    def get_status(self, nick_live_id: int) -> dict:
        return {
            "is_scanning": self.is_scanning(nick_live_id),
            "session_id": self._session_ids.get(nick_live_id),
            "comment_count": len(self._comments.get(nick_live_id, [])),
        }

    def get_comments(self, nick_live_id: int) -> list:
        return list(self._comments.get(nick_live_id, []))

    def get_queue(self, nick_live_id: int) -> asyncio.Queue:
        if nick_live_id not in self._new_comments:
            self._new_comments[nick_live_id] = asyncio.Queue()
        return self._new_comments[nick_live_id]

    def start(
        self,
        nick_live_id: int,
        session_id: int,
        cookies: str,
        poll_interval: float = 2.0,
    ) -> None:
        if self.is_scanning(nick_live_id):
            return

        self._session_ids[nick_live_id] = session_id
        self._comments[nick_live_id] = []
        self._seen_ids[nick_live_id] = set()
        self._new_comments[nick_live_id] = asyncio.Queue()

        task = asyncio.create_task(
            self._poll_loop(nick_live_id, session_id, cookies, poll_interval)
        )
        self._tasks[nick_live_id] = task

    def stop(self, nick_live_id: int) -> None:
        task = self._tasks.get(nick_live_id)
        if task and not task.done():
            task.cancel()
        self._tasks.pop(nick_live_id, None)
        self._session_ids.pop(nick_live_id, None)
        # Keep comments but close queue
        queue = self._new_comments.get(nick_live_id)
        if queue:
            queue.put_nowait(None)  # Signal end to SSE listeners

    async def _poll_loop(
        self,
        nick_live_id: int,
        session_id: int,
        cookies: str,
        poll_interval: float,
    ) -> None:
        last_ts = int(time.time())
        logger.info(f"Started scanning nick_live={nick_live_id} session={session_id}")

        try:
            while True:
                try:
                    items = await get_comments(cookies, session_id, last_ts)
                    new_items = []
                    for c in items:
                        cid = (
                            c.get("id")
                            or c.get("msg_id")
                            or c.get("msgId")
                            or f"{c.get('timestamp')}_{c.get('content')}"
                        )
                        cid = str(cid)
                        if cid not in self._seen_ids[nick_live_id]:
                            self._seen_ids[nick_live_id].add(cid)
                            self._comments[nick_live_id].append(c)
                            queue = self._new_comments.get(nick_live_id)
                            if queue:
                                await queue.put(c)
                            new_items.append(c)

                    if new_items:
                        await self._process_auto_reply(nick_live_id, session_id, new_items)

                    if items:
                        last_ts = int(time.time())

                except Exception as e:
                    logger.error(f"Poll error for nick_live={nick_live_id}: {e}")

                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            logger.info(f"Stopped scanning nick_live={nick_live_id}")

    async def _process_auto_reply(
        self, nick_live_id: int, session_id: int, comments: list
    ) -> None:
        """Check if AI reply is enabled and auto-reply to new comments."""
        from app.services.live_moderator import moderator
        from app.services.settings_service import SettingsService

        try:
            db = SessionLocal()
            try:
                svc = SettingsService(db)
                nick_settings = svc.get_or_create_nick_settings(nick_live_id)

                if nick_settings.knowledge_reply_enabled:
                    await self._process_knowledge_reply(
                        nick_live_id, session_id, comments, svc, moderator, db
                    )
                elif nick_settings.ai_reply_enabled:
                    await self._process_ai_reply(
                        nick_live_id, session_id, comments, svc, moderator
                    )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Auto-reply error for nick_live={nick_live_id}: {e}")

    async def _process_ai_reply(
        self, nick_live_id, session_id, comments, svc, moderator
    ) -> None:
        """Existing AI reply flow (unchanged logic)."""
        from app.services.ai_reply_service import generate_reply

        if not moderator.has_config(nick_live_id):
            logger.warning(f"AI reply enabled but moderator not configured for nick_live={nick_live_id}")
            return

        api_key = svc.get_openai_api_key()
        if not api_key:
            logger.warning("AI reply enabled but OpenAI API key not set")
            return

        model = svc.get_setting("openai_model") or "gpt-4o"
        system_prompt = svc.get_system_prompt() or "Bạn là nhân viên CSKH."

        for c in comments:
            content = c.get("content") or c.get("text") or ""
            if not content:
                continue

            username = (
                c.get("username")
                or c.get("userName")
                or c.get("nick_name")
                or c.get("nickname")
                or "Unknown"
            )
            user_id = c.get("streamerId") or c.get("userId") or 0

            reply_text = await generate_reply(
                api_key=api_key,
                model=model,
                system_prompt=system_prompt,
                comment_text=content,
                guest_name=username,
            )
            if reply_text:
                result = await moderator.send_reply(
                    nick_live_id, session_id, username, user_id, reply_text
                )
                logger.info(
                    f"AI reply to {username}: {reply_text[:50]}... -> {result.get('success')}"
                )
            await asyncio.sleep(1)

    async def _process_knowledge_reply(
        self, nick_live_id, session_id, comments, svc, moderator, db
    ) -> None:
        """Knowledge-based AI reply flow with product context."""
        import json

        from app.services.knowledge_product_service import KnowledgeProductService
        from app.services.knowledge_reply_service import (
            extract_product_reference,
            filter_banned_words,
            generate_knowledge_reply,
        )

        if not moderator.has_config(nick_live_id):
            logger.warning(f"Knowledge reply enabled but moderator not configured for nick_live={nick_live_id}")
            return

        kp_svc = KnowledgeProductService(db)
        products = kp_svc.get_products(nick_live_id)
        if not products:
            logger.warning(f"Knowledge reply enabled but no products for nick_live={nick_live_id}")
            return

        api_key = svc.get_openai_api_key()
        if not api_key:
            logger.warning("Knowledge reply enabled but OpenAI API key not set")
            return

        model = svc.get_knowledge_model() or svc.get_setting("openai_model") or "gpt-4o"
        banned_words = svc.get_banned_words()
        system_prompt = svc.get_knowledge_system_prompt() or svc.get_system_prompt() or None

        # Build keyword index: product_order -> keywords list
        keyword_index: dict[int, list[str]] = {}
        for p in products:
            try:
                keyword_index[p.product_order] = json.loads(p.keywords)
            except (json.JSONDecodeError, TypeError):
                keyword_index[p.product_order] = []

        for c in comments:
            content = c.get("content") or c.get("text") or ""
            if not content:
                continue

            username = (
                c.get("username")
                or c.get("userName")
                or c.get("nick_name")
                or c.get("nickname")
                or "Unknown"
            )
            user_id = c.get("streamerId") or c.get("userId") or 0

            # Step 1: Extract product reference
            product_order = extract_product_reference(content, keyword_index)

            # Step 2: Query product data
            product_context = None
            if product_order is not None:
                product = kp_svc.find_product_by_order(nick_live_id, product_order)
                if product:
                    product_context = {
                        "product_order": product.product_order,
                        "name": product.name,
                        "price_min": product.price_min,
                        "price_max": product.price_max,
                        "discount_pct": product.discount_pct,
                        "in_stock": product.in_stock,
                        "stock_qty": product.stock_qty,
                        "sold": product.sold,
                        "rating": product.rating,
                        "rating_count": product.rating_count,
                        "voucher_info": product.voucher_info,
                        "promotion_info": product.promotion_info,
                    }

            # Step 3: LLM classify + generate
            reply_text = await generate_knowledge_reply(
                api_key=api_key,
                model=model,
                comment_text=content,
                guest_name=username,
                product_context=product_context,
                system_prompt_override=system_prompt,
            )

            if reply_text:
                # Step 4: Banned words filter
                reply_text = filter_banned_words(reply_text, banned_words)

                result = await moderator.send_reply(
                    nick_live_id, session_id, username, user_id, reply_text
                )
                logger.info(
                    f"Knowledge reply to {username}: {reply_text[:50]}... -> {result.get('success')}"
                )

            await asyncio.sleep(1)


# Singleton instance
scanner = CommentScanner()
