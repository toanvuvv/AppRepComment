"""Buffered, batched writer for ReplyLog rows.

Aggregates entries in memory and flushes them to the database on a periodic
schedule (or when the buffer fills). Runs the actual DB write on a worker
thread via ``asyncio.to_thread`` so the event loop never blocks on SQL.

The ``ReplyLog`` model and ``SessionLocal`` are imported lazily inside the
sync writer to avoid import-order issues when the model module is being
created in parallel.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _write_batch_sync(entries: list[dict]) -> None:
    """Bulk-insert a batch of reply log entries.

    Imported lazily: ``ReplyLog`` and ``SessionLocal`` may not exist at
    module-load time while Agent 1 is creating the model in parallel.
    """
    from sqlalchemy import insert

    from app.database import SessionLocal  # type: ignore[import-not-found]
    from app.models.reply_log import ReplyLog  # type: ignore[import-not-found]

    with SessionLocal() as db:
        db.execute(insert(ReplyLog), entries)
        db.commit()


class ReplyLogWriter:
    """Non-blocking, batched writer for ReplyLog inserts."""

    def __init__(self, flush_interval_sec: float = 1.0, max_batch: int = 100) -> None:
        self._flush_interval: float = float(flush_interval_sec)
        self._max_batch: int = int(max_batch)
        self._safety_cap: int = self._max_batch * 10
        self._buffer: list[dict] = []
        self._lock: asyncio.Lock = asyncio.Lock()
        self._task: asyncio.Task[Any] | None = None
        self._stopping: asyncio.Event = asyncio.Event()

    # --- public API -----------------------------------------------------

    async def log(self, entry: dict) -> None:
        """Add an entry to the buffer. Non-blocking; never raises."""
        try:
            async with self._lock:
                self._buffer.append(entry)
                overflow = len(self._buffer) >= self._safety_cap
                if overflow:
                    drop_to = self._safety_cap // 2
                    dropped = len(self._buffer) - drop_to
                    # Drop oldest half to prevent OOM under sustained overload.
                    self._buffer = self._buffer[-drop_to:]
                    logger.warning(
                        "ReplyLogWriter buffer exceeded safety cap (%d); "
                        "dropped %d oldest entries",
                        self._safety_cap,
                        dropped,
                    )
        except Exception:
            logger.exception("ReplyLogWriter.log failed to enqueue entry")

    async def start(self) -> None:
        """Start the background flush loop. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(
            self._flush_loop(), name="ReplyLogWriter._flush_loop"
        )
        logger.info(
            "ReplyLogWriter started (flush_interval=%.2fs, max_batch=%d)",
            self._flush_interval,
            self._max_batch,
        )

    async def stop(self) -> None:
        """Flush any remaining entries and stop the background task."""
        self._stopping.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                logger.debug("ReplyLogWriter task stopped", exc_info=True)
        # Final drain.
        await self._flush()
        logger.info("ReplyLogWriter stopped")

    # --- internal -------------------------------------------------------

    async def _flush_loop(self) -> None:
        """Sleep + flush loop until cancelled."""
        try:
            while not self._stopping.is_set():
                try:
                    await asyncio.sleep(self._flush_interval)
                except asyncio.CancelledError:
                    raise
                await self._flush()
        except asyncio.CancelledError:
            logger.debug("ReplyLogWriter flush loop cancelled")
            raise
        except Exception:
            logger.exception("ReplyLogWriter flush loop crashed")

    async def _flush(self) -> None:
        """Swap buffer under lock, then write outside the lock."""
        async with self._lock:
            if not self._buffer:
                return
            pending = self._buffer
            self._buffer = []

        # Chunk by max_batch so one huge batch doesn't stall the worker.
        for start in range(0, len(pending), self._max_batch):
            chunk = pending[start : start + self._max_batch]
            try:
                await asyncio.to_thread(_write_batch_sync, chunk)
            except Exception:
                logger.exception(
                    "ReplyLogWriter failed to persist batch; dropping %d entries",
                    len(chunk),
                )
                # Drop the batch — requeueing would mask systemic DB failures.


# Module-level singleton.
reply_log_writer: ReplyLogWriter = ReplyLogWriter()
