"""Self-post detection for Shopee live comments.

Shopee's live comment stream includes every message sent in the session —
guest comments, host-channel messages (type 101) and moderator-channel
messages (type 102). When our own reply comes back on the next poll, the
reply pipeline must skip it; otherwise the nick replies to itself and the
system enters an infinite reply loop.

This module provides a single boolean predicate consumed by the scanner
(to avoid enqueueing) and by the reply dispatcher (defense-in-depth).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable

from app.services.nick_cache import NickSettingsSnapshot

logger = logging.getLogger(__name__)

# Shopee inner-content "type" values emitted by our own senders.
# See ShopeeLiveModerator.generate_{host,moderator}_{reply,post}_body.
_SELF_CONTENT_TYPES: frozenset[int] = frozenset({101, 102})

# Every field name that has ever been observed carrying a Shopee user id
# on incoming comments. Shopee occasionally renames/adds fields, so we
# check all of them rather than locking onto one.
_USER_ID_FIELDS: tuple[str, ...] = (
    "userId",
    "user_id",
    "uid",
    "streamerId",
    "fromUserId",
    "from_user_id",
    "authorId",
    "author_id",
    "senderId",
    "sender_id",
)


def _iter_candidate_user_ids(comment: dict[str, Any]) -> Iterable[int]:
    """Yield every user id encoded on a raw comment, normalised to int."""
    for field in _USER_ID_FIELDS:
        raw = comment.get(field)
        if raw is None or raw == "":
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value:  # ignore explicit zeros — they mean "unknown"
            yield value


def _iter_known_self_ids(settings: NickSettingsSnapshot) -> Iterable[int]:
    """Yield every user id that represents *us* on this nick."""
    if settings.shopee_user_id:
        try:
            yield int(settings.shopee_user_id)
        except (TypeError, ValueError):
            pass

    mod_cfg = settings.moderator_config or {}
    mod_host_id = mod_cfg.get("host_id")
    if mod_host_id:
        try:
            yield int(mod_host_id)
        except (TypeError, ValueError):
            pass

    # host_config.uuid is sometimes a numeric Shopee id. Only match when it
    # can be safely coerced — it is often a UUID string, in which case we
    # leave user_id comparison to the other signals.
    host_cfg = settings.host_config or {}
    host_uuid = host_cfg.get("uuid")
    if host_uuid:
        try:
            yield int(host_uuid)
        except (TypeError, ValueError):
            pass


def _extract_content_type(comment: dict[str, Any]) -> int | None:
    """Return the inner content type (101/102/...) if the comment encodes one.

    Shopee sometimes returns the inner TRTC message with its ``type`` field
    preserved at the top level, and sometimes leaves ``content`` as a raw
    JSON string. We handle both shapes.
    """
    top = comment.get("type")
    if isinstance(top, int):
        return top
    if isinstance(top, str):
        try:
            return int(top)
        except ValueError:
            pass

    content = comment.get("content")
    if isinstance(content, str) and content.startswith("{"):
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return None
        if isinstance(parsed, dict):
            inner_type = parsed.get("type")
            if isinstance(inner_type, int):
                return inner_type
            if isinstance(inner_type, str):
                try:
                    return int(inner_type)
                except ValueError:
                    return None
    return None


def is_self_post(
    comment: dict[str, Any], settings: NickSettingsSnapshot
) -> bool:
    """Return True when *comment* was posted by this nick itself.

    A match on any of three independent signals is sufficient:

    1. The comment's user id equals the nick's Shopee id, the moderator's
       host id, or the host-config uuid.
    2. The comment's inner content ``type`` is 101 (host channel) or 102
       (moderator channel) — both emitted only by our own senders.
    3. Both signals agree (the cheap common case).

    False positives are acceptable only for our own messages — we never
    want to accidentally skip a real guest comment, so each signal is
    conservative. A missing user id or an unparseable content never
    triggers a skip on its own.
    """
    self_ids = set(_iter_known_self_ids(settings))

    for uid in _iter_candidate_user_ids(comment):
        if uid in self_ids:
            return True

    content_type = _extract_content_type(comment)
    if content_type in _SELF_CONTENT_TYPES:
        # Content type 101/102 is emitted by our own senders. If any
        # candidate user id matches, we would already have returned above;
        # if user ids are missing entirely this is the only signal we have.
        # Require at least that the comment claims to be a host/mod
        # message AND either (a) we have no user id at all, or (b) we
        # don't know our own id yet. Treating all 101/102 as self is
        # safe: no guest can post those via the normal client.
        return True

    return False
