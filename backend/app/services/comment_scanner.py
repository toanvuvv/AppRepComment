import asyncio
import logging
import time
from collections import defaultdict

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

                    if items:
                        last_ts = int(time.time())

                except Exception as e:
                    logger.error(f"Poll error for nick_live={nick_live_id}: {e}")

                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            logger.info(f"Stopped scanning nick_live={nick_live_id}")


# Singleton instance
scanner = CommentScanner()
