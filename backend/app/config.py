"""Application-wide runtime constants.

Plain module-level assignments (no dataclass) so they can be imported
cheaply anywhere without side effects.
"""

import os

POLL_INTERVAL_SEC: float = 2.0
REPLY_WORKER_COUNT: int = 2
REPLY_CONCURRENCY: int = 10  # global LLM concurrency
REPLY_QUEUE_MAX: int = 500
COMMENTS_HISTORY_MAX: int = 200
SEEN_IDS_MAX: int = 3000
SHOPEE_RATE_PER_SEC: int = 25
SHOPEE_BURST: int = 50
HTTP_TIMEOUT_SEC: float = 15.0
REPLY_TIMEOUT_SEC: float = 10.0
NICK_CACHE_TTL_SEC: float = 60.0

# Reply log retention and batching
REPLY_LOG_RETENTION_HOURS: int = 24
REPLY_LOG_CLEANUP_INTERVAL_SEC: int = 3600  # cleanup runs every 1h
REPLY_LOG_FLUSH_INTERVAL_SEC: float = 1.0
REPLY_LOG_BATCH_SIZE: int = 100

# Short-TTL cache for identical comments
REPLY_CACHE_TTL_SEC: float = 15.0
REPLY_CACHE_MAX_ENTRIES: int = 2000

# Per-nick circuit breaker
CIRCUIT_WINDOW_SIZE: int = 20
CIRCUIT_ERROR_THRESHOLD: float = 0.5
CIRCUIT_OPEN_DURATION_SEC: float = 60.0

# --- Auth config ---
JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-insecure-change-me")
JWT_ALGORITHM: str = "HS256"
JWT_TTL_HOURS: int = int(os.getenv("JWT_TTL_HOURS", "8"))

ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")
ENV: str = os.getenv("ENV", "development")

if ENV != "development" and JWT_SECRET == "dev-insecure-change-me":
    raise RuntimeError("JWT_SECRET must be set in non-dev environments")
