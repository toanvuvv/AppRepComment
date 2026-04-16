"""Background comment scanner.

Polls Shopee Creator for new live comments per nick_live, deduplicates,
buffers a bounded history, and broadcasts to SSE subscribers. Reply
generation is delegated to `ReplyDispatcher` so the poll loop never
blocks on LLM latency.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict, defaultdict, deque

from app.config import COMMENTS_HISTORY_MAX, POLL_INTERVAL_SEC, SEEN_IDS_MAX
from app.services.exceptions import ShopeeAuthError, ShopeeRateLimitError
from app.services.reply_dispatcher import dispatcher
from app.services.reply_log_writer import reply_log_writer
from app.services.shopee_api import get_comments

logger = logging.getLogger(__name__)


class _LRUSet:
    """Bounded insertion-ordered set; drops oldest keys past `cap`."""

    def __init__(self, cap: int) -> None:
        if cap <= 0:
            raise ValueError("cap must be > 0")
        self._cap = cap
        self._data: OrderedDict[str, None] = OrderedDict()

    def add(self, key: str) -> None:
        if key in self._data:
            self._data.move_to_end(key)
            return
        self._data[key] = None
        if len(self._data) > self._cap:
            self._data.popitem(last=False)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)


def _comment_key(c: dict) -> str:
    """Stable dedupe key for a raw Shopee comment dict."""
    for field in ("id", "msg_id", "msgId"):
        val = c.get(field)
        if val is not None:
            return str(val)

    user_id = c.get("userId") or c.get("streamerId") or ""
    ts = c.get("timestamp") or ""
    content = c.get("content") or c.get("text") or ""
    digest_src = f"{user_id}|{ts}|{content}".encode("utf-8")
    return hashlib.md5(digest_src).hexdigest()


class CommentScanner:
    """Manages background comment polling tasks for multiple nick lives."""

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}
        self._session_ids: dict[int, int] = {}
        self._comments: dict[int, deque] = {}
        self._seen_ids: dict[int, _LRUSet] = {}
        self._subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)
        self._locks: dict[int, asyncio.Lock] = {}

        # Backward-compat alias: older tests/touch points may still look at
        # `_new_comments`. Shares identity with `_subscribers`.
        self._new_comments = self._subscribers

    # --- status --------------------------------------------------------

    def is_scanning(self, nick_live_id: int) -> bool:
        task = self._tasks.get(nick_live_id)
        return task is not None and not task.done()

    def get_status(self, nick_live_id: int) -> dict:
        history = self._comments.get(nick_live_id)
        return {
            "is_scanning": self.is_scanning(nick_live_id),
            "session_id": self._session_ids.get(nick_live_id),
            "comment_count": len(history) if history is not None else 0,
        }

    def get_comments(self, nick_live_id: int) -> list:
        history = self._comments.get(nick_live_id)
        if history is None:
            return []
        return list(history)

    # --- subscriptions -------------------------------------------------

    def subscribe(self, nick_live_id: int) -> asyncio.Queue:
        """Register a new SSE subscriber queue for the given nick."""
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers[nick_live_id].add(q)
        return q

    def unsubscribe(self, nick_live_id: int, queue: asyncio.Queue) -> None:
        subs = self._subscribers.get(nick_live_id)
        if subs is not None:
            subs.discard(queue)

    def get_queue(self, nick_live_id: int) -> asyncio.Queue:
        """Backward-compat: returns a newly-subscribed queue.

        Prefer `subscribe(...)` + `unsubscribe(...)` in new code.
        """
        return self.subscribe(nick_live_id)

    def _broadcast(self, nick_live_id: int, comment: dict) -> None:
        for q in list(self._subscribers.get(nick_live_id, ())):
            try:
                q.put_nowait(comment)
            except asyncio.QueueFull:
                logger.warning(
                    f"Slow SSE consumer for nick={nick_live_id}; dropping"
                )

    # --- lifecycle -----------------------------------------------------

    def start(
        self,
        nick_live_id: int,
        session_id: int,
        cookies: str,
        poll_interval: float = POLL_INTERVAL_SEC,
    ) -> None:
        """Idempotently start the poll loop for a nick.

        Sync by design: the entire body runs without an `await`, so in a
        single-threaded asyncio loop concurrent callers cannot interleave.
        """
        if self.is_scanning(nick_live_id):
            return

        self._session_ids[nick_live_id] = session_id
        self._comments[nick_live_id] = deque(maxlen=COMMENTS_HISTORY_MAX)
        self._seen_ids[nick_live_id] = _LRUSet(cap=SEEN_IDS_MAX)
        self._subscribers.setdefault(nick_live_id, set())

        # Start reply dispatcher BEFORE scheduling the poll task so the
        # first enqueue from the loop already has workers ready.
        dispatcher.start(nick_live_id, session_id, cookies)

        task = asyncio.create_task(
            self._poll_loop(nick_live_id, session_id, cookies, poll_interval),
            name=f"scanner-poll-{nick_live_id}",
        )
        self._tasks[nick_live_id] = task
        logger.info(
            f"Started scanner for nick_live={nick_live_id} session={session_id}"
        )

    def stop(self, nick_live_id: int) -> None:
        """Stop scanning and notify subscribers."""
        task = self._tasks.pop(nick_live_id, None)
        if task is not None and not task.done():
            task.cancel()

        # Signal SSE subscribers that the stream is done.
        for q in list(self._subscribers.get(nick_live_id, ())):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                logger.debug(
                    f"Subscriber queue full at stop for nick={nick_live_id}"
                )

        dispatcher.stop(nick_live_id)

        self._session_ids.pop(nick_live_id, None)
        self._seen_ids.pop(nick_live_id, None)
        # grace retention: keep _comments history so callers can still
        # read the final buffer after stop(). It's reset on the next start().
        logger.info(f"Stopped scanner for nick_live={nick_live_id}")

    # Back-compat shim: the pre-Wave-2 path called this method from the
    # poll loop. The new implementation delegates to `ReplyDispatcher`
    # instead, so this method is intentionally a no-op. Kept so existing
    # tests (and any external monkey-patch) can still target it.
    async def _process_auto_reply(
        self, nick_live_id: int, session_id: int, comments: list
    ) -> None:
        return None

    # --- poll loop -----------------------------------------------------

    async def _poll_loop(
        self,
        nick_live_id: int,
        session_id: int,
        cookies: str,
        poll_interval: float,
    ) -> None:
        last_ts = int(time.time())
        backoff = 0.0

        try:
            while True:
                try:
                    if backoff > 0:
                        await asyncio.sleep(backoff)
                        backoff = 0.0

                    items = await get_comments(cookies, session_id, last_ts)

                    history = self._comments.get(nick_live_id)
                    seen = self._seen_ids.get(nick_live_id)
                    if history is None or seen is None:
                        # We were stopped mid-poll.
                        break

                    new_items: list[dict] = []
                    for c in items:
                        key = _comment_key(c)
                        if key in seen:
                            continue
                        seen.add(key)
                        history.append(c)
                        self._broadcast(nick_live_id, c)
                        new_items.append(c)

                    # Delegate reply handling — never blocks polling.
                    for c in new_items:
                        if not await dispatcher.enqueue(nick_live_id, c):
                            await reply_log_writer.log({
                                "nick_live_id": nick_live_id,
                                "session_id": session_id,
                                "guest_name": c.get("username")
                                or c.get("userName")
                                or "Unknown",
                                "guest_id": str(
                                    c.get("userId") or c.get("streamerId") or ""
                                ),
                                "comment_text": c.get("content") or c.get("text"),
                                "reply_text": None,
                                "reply_type": None,
                                "outcome": "dropped",
                                "error": "reply_queue_full",
                            })

                    if items:
                        max_ts = max(
                            (int(c.get("timestamp") or 0) for c in items),
                            default=last_ts,
                        )
                        # 5s safety window to avoid dropping late-arriving
                        # comments around clock drift.
                        last_ts = max(last_ts, max_ts - 5)

                except ShopeeAuthError as e:
                    logger.error(
                        f"Auth expired for nick_live={nick_live_id}: {e}; "
                        f"stopping scanner"
                    )
                    break
                except ShopeeRateLimitError:
                    logger.warning(
                        f"Rate limited on nick_live={nick_live_id}; "
                        f"backing off 30s"
                    )
                    backoff = 30.0
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        f"Poll error for nick_live={nick_live_id}"
                    )

                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            logger.info(f"Cancelled scanner for nick_live={nick_live_id}")
            raise
        finally:
            logger.debug(f"Poll loop exiting for nick_live={nick_live_id}")


# Singleton instance
scanner = CommentScanner()
