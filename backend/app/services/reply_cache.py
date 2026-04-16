"""Short-TTL cache for identical comments (per nick).

Avoids redundant LLM calls when several viewers post the same (or
near-identical) comment in a short window. Pure sync — all ops are
fast dict manipulations and safe to call from inside the event loop.
"""
from __future__ import annotations

import logging
import re
import string
import time

logger = logging.getLogger(__name__)


_MAX_NORMALIZED_LEN: int = 80
_WS_RE: re.Pattern[str] = re.compile(r"\s+")
# Translation table that strips ASCII punctuation but preserves Unicode
# (so Vietnamese accents/tone marks stay intact — they carry meaning).
_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


class ReplyCache:
    """In-memory TTL cache keyed by (nick_live_id, normalized_content)."""

    def __init__(self, ttl_sec: float = 15.0, max_entries: int = 2000) -> None:
        self._ttl: float = float(ttl_sec)
        self._max_entries: int = int(max_entries)
        # key -> (reply_text, expires_at monotonic seconds)
        self._store: dict[tuple[int, str], tuple[str, float]] = {}

    # --- public API -----------------------------------------------------

    def normalize(self, content: str) -> str:
        """Lowercase, strip punctuation, collapse whitespace, truncate to 80 chars.

        Preserves Unicode characters (Vietnamese accents are meaningful).
        """
        if not content:
            return ""
        text = content.lower()
        text = text.translate(_PUNCT_TABLE)
        text = _WS_RE.sub(" ", text).strip()
        if len(text) > _MAX_NORMALIZED_LEN:
            text = text[:_MAX_NORMALIZED_LEN]
        return text

    def get(self, nick_live_id: int, content: str) -> str | None:
        """Return cached reply_text if unexpired; else None."""
        key = (nick_live_id, self.normalize(content))
        entry = self._store.get(key)
        if entry is None:
            return None
        reply_text, expires_at = entry
        if expires_at < time.monotonic():
            self._store.pop(key, None)
            return None
        return reply_text

    def put(self, nick_live_id: int, content: str, reply_text: str) -> None:
        """Store a reply keyed by normalized content."""
        if len(self._store) >= self._max_entries:
            self._evict_expired()
            if len(self._store) >= self._max_entries:
                self._evict_oldest_fraction(0.2)

        key = (nick_live_id, self.normalize(content))
        self._store[key] = (reply_text, time.monotonic() + self._ttl)

    def size(self) -> int:
        return len(self._store)

    # --- internal -------------------------------------------------------

    def _evict_expired(self) -> None:
        """Drop expired entries. Called opportunistically."""
        now = time.monotonic()
        expired_keys = [k for k, (_, exp) in self._store.items() if exp < now]
        for k in expired_keys:
            self._store.pop(k, None)
        if expired_keys:
            logger.debug("ReplyCache evicted %d expired entries", len(expired_keys))

    def _evict_oldest_fraction(self, fraction: float) -> None:
        """Drop the oldest ``fraction`` of entries (by expires_at ascending)."""
        if not self._store:
            return
        count = max(1, int(len(self._store) * fraction))
        # Sort by expires_at (oldest first) and drop the first `count`.
        oldest = sorted(self._store.items(), key=lambda kv: kv[1][1])[:count]
        for k, _ in oldest:
            self._store.pop(k, None)
        logger.debug(
            "ReplyCache hit max_entries (%d); evicted %d oldest entries",
            self._max_entries,
            count,
        )


# Module-level singleton.
reply_cache: ReplyCache = ReplyCache()
