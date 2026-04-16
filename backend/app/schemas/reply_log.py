from datetime import datetime

from pydantic import BaseModel


class ReplyLogResponse(BaseModel):
    id: int
    nick_live_id: int
    session_id: int
    guest_name: str | None
    guest_id: str | None
    comment_text: str | None
    reply_text: str | None
    reply_type: str | None
    outcome: str
    status_code: int | None
    error: str | None
    product_order: int | None
    latency_ms: int | None
    llm_latency_ms: int | None
    retry_count: int
    cached_hit: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ReplyLogStats(BaseModel):
    total: int
    success: int
    failed: int
    dropped: int
    circuit_open: int
    no_config: int
    # success / (success + failed); 0.0 when denominator is zero
    success_rate: float
    # cached_hit=true / total replies; 0.0 when total is zero
    cache_hit_rate: float
    avg_latency_ms: float | None
    p50_latency_ms: int | None
    p95_latency_ms: int | None
    since: datetime
    until: datetime


class ReplyLogCreate(BaseModel):
    """Internal schema used by the dispatcher when logging a reply attempt.

    Mirrors the dict shape of entries enqueued in the dispatcher's write
    buffer before they are flushed to the reply_logs table.
    """

    nick_live_id: int
    session_id: int
    guest_name: str | None = None
    guest_id: str | None = None
    comment_text: str | None = None
    reply_text: str | None = None
    reply_type: str | None = None
    outcome: str
    status_code: int | None = None
    error: str | None = None
    product_order: int | None = None
    latency_ms: int | None = None
    llm_latency_ms: int | None = None
    retry_count: int = 0
    cached_hit: bool = False
