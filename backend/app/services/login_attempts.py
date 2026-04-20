"""In-memory tracker of failed login attempts per IP.

Not persistent; resets on restart. Adequate for a single-instance deploy.
Successful logins reset the counter for the IP so legitimate users are
never locked out by their own successful session.
"""

from collections import defaultdict, deque
from threading import Lock
from time import monotonic

_WINDOW_SECONDS = 15 * 60
_MAX_FAILURES = 5

_attempts: dict[str, deque[float]] = defaultdict(deque)
_lock = Lock()


def record_failure(ip: str) -> None:
    with _lock:
        q = _attempts[ip]
        q.append(monotonic())
        _prune(q)


def is_rate_limited(ip: str) -> bool:
    with _lock:
        q = _attempts[ip]
        _prune(q)
        return len(q) >= _MAX_FAILURES


def reset(ip: str | None = None) -> None:
    """Reset counters. Pass ip=None to clear all (used in tests)."""
    with _lock:
        if ip is None:
            _attempts.clear()
        else:
            _attempts.pop(ip, None)


def _prune(q: deque[float]) -> None:
    cutoff = monotonic() - _WINDOW_SECONDS
    while q and q[0] < cutoff:
        q.popleft()
