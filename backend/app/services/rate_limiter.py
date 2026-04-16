"""Async token-bucket rate limiter for outbound Shopee traffic."""
from __future__ import annotations

import asyncio
import time

from app.config import SHOPEE_BURST, SHOPEE_RATE_PER_SEC


class TokenBucket:
    """Simple async token bucket.

    - Tokens refill at `rate_per_sec` up to `burst`.
    - `acquire()` blocks until at least one token is available, then
      decrements the counter.
    """

    def __init__(self, rate_per_sec: float, burst: int) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be > 0")
        if burst <= 0:
            raise ValueError("burst must be > 0")

        self._rate: float = float(rate_per_sec)
        self._burst: int = int(burst)
        self._tokens: float = float(burst)
        self._last_refill: float = time.monotonic()
        self._lock: asyncio.Lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until a token is available, then consume one."""
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                if elapsed > 0:
                    self._tokens = min(
                        float(self._burst), self._tokens + elapsed * self._rate
                    )
                    self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                # Compute how long we need to wait for one full token.
                deficit = 1.0 - self._tokens
                wait_time = deficit / self._rate

            # Release the lock while sleeping so other callers can also
            # observe refills.
            await asyncio.sleep(wait_time)


# Singleton bucket shared by all Shopee API callers in this process.
shopee_limiter: TokenBucket = TokenBucket(SHOPEE_RATE_PER_SEC, SHOPEE_BURST)
