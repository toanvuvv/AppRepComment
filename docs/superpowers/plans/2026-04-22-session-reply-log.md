# Session-based Reply Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho phép user xem/clear reply log theo từng session live riêng cho từng nick, với retention tự động 3 ngày.

**Architecture:** Thêm 3 endpoint (GET sessions list, GET logs with session filter, DELETE session), bật filter session trong hook FE, thêm dropdown + Clear button trong Reply Logs modal. Retention 3 ngày = sửa 1 config var (cleanup loop đã tồn tại).

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + Ant Design + axios (frontend), pytest.

**Spec:** [`docs/superpowers/specs/2026-04-22-session-reply-log-design.md`](../specs/2026-04-22-session-reply-log-design.md)

---

## File Structure

### Backend
- **Modify** `backend/app/config.py` — retention 24h → 72h.
- **Modify** `backend/app/models/reply_log.py` — cập nhật docstring retention.
- **Modify** `backend/app/schemas/reply_log.py` — thêm `ReplyLogSessionSummary`.
- **Modify** `backend/app/routers/reply_logs.py` — thêm GET `/sessions`, filter `session_id` vào GET `""`, thêm DELETE `""`.
- **Create** `backend/tests/test_reply_logs_sessions.py` — test GET sessions + filter session_id.
- **Create** `backend/tests/test_reply_logs_delete.py` — test DELETE session + ownership.
- **Create** `backend/tests/test_reply_log_retention.py` — test cutoff = 72h.

### Frontend
- **Modify** `frontend/src/api/replyLogs.ts` — thêm `ReplyLogSession`, `listReplyLogSessions`, `deleteReplyLogSession`, thêm `session_id` vào `ListReplyLogsParams`.
- **Create** `frontend/src/hooks/useReplyLogSessions.ts` — hook poll sessions list.
- **Modify** `frontend/src/hooks/useReplyLogs.ts` — signature nhận `sessionId: number | null`.
- **Modify** `frontend/src/pages/LiveScan.tsx` — Reply Logs modal có dropdown session + nút Clear.

---

## Task 1: Backend — schema cho session summary

**Files:**
- Modify: `backend/app/schemas/reply_log.py`

- [ ] **Step 1: Đọc file hiện tại**

Run: `Read backend/app/schemas/reply_log.py`
Expected: thấy các schema hiện có (`ReplyLogResponse`, `ReplyLogStats`).

- [ ] **Step 2: Thêm schema mới ở cuối file**

```python
from datetime import datetime
from pydantic import BaseModel


class ReplyLogSessionSummary(BaseModel):
    """Tóm tắt 1 session live: range thời gian và số reply đã log."""

    session_id: int
    first_at: datetime
    last_at: datetime
    count: int

    model_config = {"from_attributes": True}
```

(Nếu file đã import BaseModel / datetime ở đầu thì KHÔNG import lại — chỉ append class.)

- [ ] **Step 3: Commit**

```bash
rtk git add backend/app/schemas/reply_log.py
rtk git commit -m "feat(be): ReplyLogSessionSummary schema"
```

---

## Task 2: Backend — GET `/api/reply-logs/sessions`

**Files:**
- Modify: `backend/app/routers/reply_logs.py`
- Test: `backend/tests/test_reply_logs_sessions.py`

- [ ] **Step 1: Viết failing test — list sessions đúng thứ tự**

Tạo file mới `backend/tests/test_reply_logs_sessions.py`:

```python
"""Tests for GET /api/reply-logs/sessions and session_id filter."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.nick_live import NickLive
from app.models.reply_log import ReplyLog
from app.models.user import User
from app.services.auth import hash_password

USERNAMES = ["rls_owner", "rls_other"]
client = TestClient(app)


@pytest.fixture(autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(ReplyLog).delete()
        db.query(NickLive).filter(
            NickLive.user_id.in_(db.query(User.id).filter(User.username.in_(USERNAMES)))
        ).delete(synchronize_session=False)
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.add(User(username="rls_owner", password_hash=hash_password("pw12345678"), role="user", max_nicks=10))
        db.add(User(username="rls_other", password_hash=hash_password("pw12345678"), role="user", max_nicks=10))
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(ReplyLog).delete()
        db.query(NickLive).filter(
            NickLive.user_id.in_(db.query(User.id).filter(User.username.in_(USERNAMES)))
        ).delete(synchronize_session=False)
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.commit()


def _login(u, p="pw12345678"):
    return client.post("/api/auth/login", json={"username": u, "password": p}).json()["access_token"]


def _hdr(t):
    return {"Authorization": f"Bearer {t}"}


def _user_id(u):
    with SessionLocal() as db:
        return db.query(User).filter_by(username=u).first().id


def _make_nick(user_id: int) -> int:
    with SessionLocal() as db:
        n = NickLive(user_id=user_id, name="n", shopee_user_id=1, cookies="c")
        db.add(n)
        db.commit()
        db.refresh(n)
        return n.id


def _insert_log(nick_id: int, session_id: int, created_at: datetime) -> None:
    with SessionLocal() as db:
        db.add(ReplyLog(
            nick_live_id=nick_id,
            session_id=session_id,
            outcome="success",
            created_at=created_at,
        ))
        db.commit()


def test_list_sessions_groups_and_orders_by_last_at_desc():
    tok = _login("rls_owner")
    nick = _make_nick(_user_id("rls_owner"))
    now = datetime.now(timezone.utc)

    # Session 100: 2 logs from 2h ago to 1h ago
    _insert_log(nick, 100, now - timedelta(hours=2))
    _insert_log(nick, 100, now - timedelta(hours=1))
    # Session 200: 1 log from 30m ago (newest)
    _insert_log(nick, 200, now - timedelta(minutes=30))

    r = client.get(f"/api/reply-logs/sessions?nick_live_id={nick}", headers=_hdr(tok))
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) == 2
    assert data[0]["session_id"] == 200
    assert data[0]["count"] == 1
    assert data[1]["session_id"] == 100
    assert data[1]["count"] == 2
```

- [ ] **Step 2: Run test — expect FAIL (endpoint chưa có)**

Run: `cd backend && rtk pytest tests/test_reply_logs_sessions.py::test_list_sessions_groups_and_orders_by_last_at_desc -v`
Expected: FAIL với 404 hoặc `AssertionError`.

- [ ] **Step 3: Implement endpoint trong `backend/app/routers/reply_logs.py`**

Thêm import ở đầu (cùng block import):
```python
from sqlalchemy import func

from app.schemas.reply_log import ReplyLogResponse, ReplyLogSessionSummary, ReplyLogStats
```

Thêm endpoint mới (đặt sau `list_reply_logs`, trước `reply_log_stats`):

```python
@router.get("/sessions", response_model=list[ReplyLogSessionSummary])
def list_reply_log_sessions(
    nick_live_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ReplyLogSessionSummary]:
    """Group reply logs theo session_id cho 1 nick. Newest session first."""
    owned = _owned_nick_ids(current_user.id, db)
    rows = (
        db.query(
            ReplyLog.session_id.label("session_id"),
            func.min(ReplyLog.created_at).label("first_at"),
            func.max(ReplyLog.created_at).label("last_at"),
            func.count(ReplyLog.id).label("count"),
        )
        .filter(ReplyLog.nick_live_id == nick_live_id)
        .filter(ReplyLog.nick_live_id.in_(owned))
        .group_by(ReplyLog.session_id)
        .order_by(func.max(ReplyLog.created_at).desc())
        .all()
    )
    return [
        ReplyLogSessionSummary(
            session_id=r.session_id,
            first_at=r.first_at,
            last_at=r.last_at,
            count=r.count,
        )
        for r in rows
    ]
```

- [ ] **Step 4: Run test — expect PASS**

Run: `cd backend && rtk pytest tests/test_reply_logs_sessions.py::test_list_sessions_groups_and_orders_by_last_at_desc -v`
Expected: PASS.

- [ ] **Step 5: Thêm test ownership**

Append vào `test_reply_logs_sessions.py`:

```python
def test_list_sessions_ownership_hides_other_users_nicks():
    tok_owner = _login("rls_owner")
    tok_other = _login("rls_other")
    nick = _make_nick(_user_id("rls_owner"))
    _insert_log(nick, 100, datetime.now(timezone.utc))

    r = client.get(f"/api/reply-logs/sessions?nick_live_id={nick}", headers=_hdr(tok_other))
    assert r.status_code == 200
    assert r.json() == []

    r = client.get(f"/api/reply-logs/sessions?nick_live_id={nick}", headers=_hdr(tok_owner))
    assert r.status_code == 200
    assert len(r.json()) == 1
```

- [ ] **Step 6: Run cả file**

Run: `cd backend && rtk pytest tests/test_reply_logs_sessions.py -v`
Expected: 2 PASS.

- [ ] **Step 7: Commit**

```bash
rtk git add backend/app/routers/reply_logs.py backend/tests/test_reply_logs_sessions.py
rtk git commit -m "feat(be): GET /api/reply-logs/sessions endpoint"
```

---

## Task 3: Backend — filter `session_id` cho GET `/api/reply-logs`

**Files:**
- Modify: `backend/app/routers/reply_logs.py:42-69`
- Test: `backend/tests/test_reply_logs_sessions.py`

- [ ] **Step 1: Thêm failing test**

Append vào `test_reply_logs_sessions.py`:

```python
def test_list_logs_filters_by_session_id():
    tok = _login("rls_owner")
    nick = _make_nick(_user_id("rls_owner"))
    now = datetime.now(timezone.utc)
    _insert_log(nick, 100, now - timedelta(minutes=5))
    _insert_log(nick, 100, now - timedelta(minutes=4))
    _insert_log(nick, 200, now - timedelta(minutes=3))

    r = client.get(
        f"/api/reply-logs?nick_live_id={nick}&session_id=100",
        headers=_hdr(tok),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) == 2
    assert all(row["session_id"] == 100 for row in data)
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd backend && rtk pytest tests/test_reply_logs_sessions.py::test_list_logs_filters_by_session_id -v`
Expected: FAIL (trả 3 thay vì 2, vì param chưa được filter).

- [ ] **Step 3: Sửa `list_reply_logs` trong `backend/app/routers/reply_logs.py`**

Thêm param `session_id` vào signature (sau `nick_live_id`):

```python
@router.get("", response_model=list[ReplyLogResponse])
def list_reply_logs(
    nick_live_id: int | None = None,
    session_id: int | None = None,
    outcome: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ReplyLog]:
    """List reply log rows, newest first."""
    owned = _owned_nick_ids(current_user.id, db)
    q = db.query(ReplyLog).filter(ReplyLog.nick_live_id.in_(owned))
    if nick_live_id is not None:
        q = q.filter(ReplyLog.nick_live_id == nick_live_id)
    if session_id is not None:
        q = q.filter(ReplyLog.session_id == session_id)
    if outcome:
        q = q.filter(ReplyLog.outcome == outcome)
    if since is not None:
        q = q.filter(ReplyLog.created_at >= since)
    if until is not None:
        q = q.filter(ReplyLog.created_at <= until)
    return (
        q.order_by(ReplyLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
```

- [ ] **Step 4: Run test — expect PASS**

Run: `cd backend && rtk pytest tests/test_reply_logs_sessions.py::test_list_logs_filters_by_session_id -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add backend/app/routers/reply_logs.py backend/tests/test_reply_logs_sessions.py
rtk git commit -m "feat(be): session_id filter trong GET /api/reply-logs"
```

---

## Task 4: Backend — DELETE `/api/reply-logs`

**Files:**
- Modify: `backend/app/routers/reply_logs.py`
- Test: `backend/tests/test_reply_logs_delete.py`

- [ ] **Step 1: Viết failing test**

Tạo `backend/tests/test_reply_logs_delete.py`:

```python
"""Tests for DELETE /api/reply-logs."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.nick_live import NickLive
from app.models.reply_log import ReplyLog
from app.models.user import User
from app.services.auth import hash_password

USERNAMES = ["rld_owner", "rld_other"]
client = TestClient(app)


@pytest.fixture(autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(ReplyLog).delete()
        db.query(NickLive).filter(
            NickLive.user_id.in_(db.query(User.id).filter(User.username.in_(USERNAMES)))
        ).delete(synchronize_session=False)
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.add(User(username="rld_owner", password_hash=hash_password("pw12345678"), role="user", max_nicks=10))
        db.add(User(username="rld_other", password_hash=hash_password("pw12345678"), role="user", max_nicks=10))
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(ReplyLog).delete()
        db.query(NickLive).filter(
            NickLive.user_id.in_(db.query(User.id).filter(User.username.in_(USERNAMES)))
        ).delete(synchronize_session=False)
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.commit()


def _login(u, p="pw12345678"):
    return client.post("/api/auth/login", json={"username": u, "password": p}).json()["access_token"]


def _hdr(t):
    return {"Authorization": f"Bearer {t}"}


def _user_id(u):
    with SessionLocal() as db:
        return db.query(User).filter_by(username=u).first().id


def _make_nick(user_id: int) -> int:
    with SessionLocal() as db:
        n = NickLive(user_id=user_id, name="n", shopee_user_id=1, cookies="c")
        db.add(n)
        db.commit()
        db.refresh(n)
        return n.id


def _insert_log(nick_id: int, session_id: int) -> None:
    with SessionLocal() as db:
        db.add(ReplyLog(
            nick_live_id=nick_id,
            session_id=session_id,
            outcome="success",
            created_at=datetime.now(timezone.utc),
        ))
        db.commit()


def _count_logs(nick_id: int, session_id: int) -> int:
    with SessionLocal() as db:
        return (
            db.query(ReplyLog)
            .filter(ReplyLog.nick_live_id == nick_id, ReplyLog.session_id == session_id)
            .count()
        )


def test_delete_removes_only_target_session():
    tok = _login("rld_owner")
    nick = _make_nick(_user_id("rld_owner"))
    _insert_log(nick, 100)
    _insert_log(nick, 100)
    _insert_log(nick, 200)

    r = client.delete(
        f"/api/reply-logs?nick_live_id={nick}&session_id=100",
        headers=_hdr(tok),
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": 2}
    assert _count_logs(nick, 100) == 0
    assert _count_logs(nick, 200) == 1


def test_delete_404_when_nick_not_owned():
    tok_other = _login("rld_other")
    nick = _make_nick(_user_id("rld_owner"))
    _insert_log(nick, 100)

    r = client.delete(
        f"/api/reply-logs?nick_live_id={nick}&session_id=100",
        headers=_hdr(tok_other),
    )
    assert r.status_code == 404
    assert _count_logs(nick, 100) == 1
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd backend && rtk pytest tests/test_reply_logs_delete.py -v`
Expected: FAIL (endpoint chưa có → 405 Method Not Allowed).

- [ ] **Step 3: Thêm endpoint DELETE vào `backend/app/routers/reply_logs.py`**

Thêm import ở đầu:
```python
from fastapi import APIRouter, Depends, HTTPException, Query
```
(HTTPException có thể đã có; đảm bảo import.)

Thêm endpoint mới (đặt cuối file, sau `reply_log_stats`):

```python
@router.delete("")
def delete_reply_log_session(
    nick_live_id: int = Query(..., gt=0),
    session_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Xóa toàn bộ reply log của 1 session cho 1 nick.

    Trả 404 nếu nick không thuộc user hiện tại.
    """
    owns = (
        db.query(NickLive.id)
        .filter(NickLive.id == nick_live_id, NickLive.user_id == current_user.id)
        .first()
    )
    if owns is None:
        raise HTTPException(status_code=404, detail="nick_live not found")

    deleted = (
        db.query(ReplyLog)
        .filter(
            ReplyLog.nick_live_id == nick_live_id,
            ReplyLog.session_id == session_id,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": int(deleted or 0)}
```

- [ ] **Step 4: Run test — expect PASS**

Run: `cd backend && rtk pytest tests/test_reply_logs_delete.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add backend/app/routers/reply_logs.py backend/tests/test_reply_logs_delete.py
rtk git commit -m "feat(be): DELETE /api/reply-logs để clear session"
```

---

## Task 5: Backend — retention 3 ngày

**Files:**
- Modify: `backend/app/config.py:22`
- Modify: `backend/app/models/reply_log.py:10-15`
- Test: `backend/tests/test_reply_log_retention.py`

- [ ] **Step 1: Viết test retention**

Tạo `backend/tests/test_reply_log_retention.py`:

```python
"""Test retention cutoff = 72h (3 ngày)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.config import REPLY_LOG_RETENTION_HOURS
from app.database import Base, SessionLocal, engine
from app.main import _delete_logs_before
from app.models.nick_live import NickLive
from app.models.reply_log import ReplyLog
from app.models.user import User
from app.services.auth import hash_password


@pytest.fixture(autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(ReplyLog).delete()
        db.query(NickLive).filter(
            NickLive.user_id.in_(db.query(User.id).filter(User.username == "rlr_owner"))
        ).delete(synchronize_session=False)
        db.query(User).filter(User.username == "rlr_owner").delete()
        u = User(username="rlr_owner", password_hash=hash_password("pw12345678"), role="user", max_nicks=10)
        db.add(u)
        db.commit()
        db.refresh(u)
        n = NickLive(user_id=u.id, name="n", shopee_user_id=1, cookies="c")
        db.add(n)
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(ReplyLog).delete()
        db.query(NickLive).filter(
            NickLive.user_id.in_(db.query(User.id).filter(User.username == "rlr_owner"))
        ).delete(synchronize_session=False)
        db.query(User).filter(User.username == "rlr_owner").delete()
        db.commit()


def test_retention_is_72_hours():
    assert REPLY_LOG_RETENTION_HOURS == 72


def test_delete_logs_before_cutoff_keeps_recent_rows():
    with SessionLocal() as db:
        nick_id = db.query(NickLive.id).filter(NickLive.user_id == db.query(User.id).filter(User.username == "rlr_owner").scalar()).scalar()
        now = datetime.now(timezone.utc)
        db.add(ReplyLog(nick_live_id=nick_id, session_id=1, outcome="success", created_at=now - timedelta(hours=71)))
        db.add(ReplyLog(nick_live_id=nick_id, session_id=1, outcome="success", created_at=now - timedelta(hours=73)))
        db.commit()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
    deleted = _delete_logs_before(cutoff)
    assert deleted == 1

    with SessionLocal() as db:
        remaining = db.query(ReplyLog).count()
        assert remaining == 1
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd backend && rtk pytest tests/test_reply_log_retention.py::test_retention_is_72_hours -v`
Expected: FAIL (giá trị đang là 24).

- [ ] **Step 3: Sửa config**

Trong `backend/app/config.py` đổi:
```python
REPLY_LOG_RETENTION_HOURS: int = 24
```
thành:
```python
REPLY_LOG_RETENTION_HOURS: int = 72  # 3 days
```

- [ ] **Step 4: Update docstring model**

Trong `backend/app/models/reply_log.py`, thay khối docstring class:
```python
    """Persisted log of every reply attempt by the dispatcher.

    Retained ~24h for debugging and monitoring. Populated by the reply
    dispatcher for success, failure, dropped, cached-hit, circuit-open,
    and no-config outcomes.
    """
```
thành:
```python
    """Persisted log of every reply attempt by the dispatcher.

    Retained 3 days (72h) via main._reply_log_cleanup_loop. Populated by
    the reply dispatcher for success, failure, dropped, cached-hit,
    circuit-open, and no-config outcomes.
    """
```

- [ ] **Step 5: Run — expect PASS**

Run: `cd backend && rtk pytest tests/test_reply_log_retention.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add backend/app/config.py backend/app/models/reply_log.py backend/tests/test_reply_log_retention.py
rtk git commit -m "feat(be): retention reply_log 24h -> 72h (3 days)"
```

---

## Task 6: Backend — chạy toàn bộ test suite để đảm bảo không regress

- [ ] **Step 1: Run full backend suite**

Run: `cd backend && rtk pytest -x`
Expected: tất cả test PASS (có test hiện hữu có thể assert 24h → chạy để phát hiện; nếu có fail do retention đổi, sửa test đó cho đúng).

- [ ] **Step 2: Nếu có test fail do thay đổi retention**

Grep tìm: `rtk grep -r "REPLY_LOG_RETENTION_HOURS" backend/` và `rtk grep -rn "24h\|24 hours" backend/tests/`. Với mỗi test assert giá trị cụ thể 24, cập nhật thành 72 và commit riêng:
```bash
rtk git commit -m "test: cập nhật assert retention 24h -> 72h"
```

- [ ] **Step 3: Chạy lại full suite**

Run: `cd backend && rtk pytest`
Expected: all PASS.

---

## Task 7: Frontend API — types + client functions

**Files:**
- Modify: `frontend/src/api/replyLogs.ts`

- [ ] **Step 1: Đọc file**

Run: `Read frontend/src/api/replyLogs.ts`

- [ ] **Step 2: Thêm types và functions**

Sửa interface `ListReplyLogsParams`, thêm `session_id`:

```typescript
export interface ListReplyLogsParams {
  nick_live_id?: number;
  session_id?: number;
  outcome?: ReplyOutcome;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
}
```

Append cuối file:

```typescript
export interface ReplyLogSession {
  session_id: number;
  first_at: string;
  last_at: string;
  count: number;
}

export async function listReplyLogSessions(
  nickLiveId: number
): Promise<ReplyLogSession[]> {
  const res = await apiClient.get("/reply-logs/sessions", {
    params: { nick_live_id: nickLiveId },
  });
  return res.data;
}

export async function deleteReplyLogSession(
  nickLiveId: number,
  sessionId: number
): Promise<{ deleted: number }> {
  const res = await apiClient.delete("/reply-logs", {
    params: { nick_live_id: nickLiveId, session_id: sessionId },
  });
  return res.data;
}
```

- [ ] **Step 3: Kiểm tra build FE**

Run: `cd frontend && rtk npx tsc --noEmit`
Expected: không có type error mới.

- [ ] **Step 4: Commit**

```bash
rtk git add frontend/src/api/replyLogs.ts
rtk git commit -m "feat(fe): reply-log session API client"
```

---

## Task 8: Frontend hook — `useReplyLogSessions`

**Files:**
- Create: `frontend/src/hooks/useReplyLogSessions.ts`

- [ ] **Step 1: Tạo file mới**

```typescript
import { useCallback, useEffect, useRef, useState } from "react";
import { listReplyLogSessions, type ReplyLogSession } from "../api/replyLogs";

const POLL_INTERVAL_MS = 2500;

export interface UseReplyLogSessionsResult {
  sessions: ReplyLogSession[];
  refresh: () => void;
}

export function useReplyLogSessions(
  nickLiveId: number | null,
  enabled: boolean
): UseReplyLogSessionsResult {
  const [sessions, setSessions] = useState<ReplyLogSession[]>([]);
  const cancelledRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchOnce = useCallback(async () => {
    if (nickLiveId === null) return;
    try {
      const data = await listReplyLogSessions(nickLiveId);
      if (cancelledRef.current) return;
      setSessions(data);
    } catch {
      // Silent — polling retries
    }
  }, [nickLiveId]);

  const refresh = useCallback(() => {
    fetchOnce();
  }, [fetchOnce]);

  useEffect(() => {
    cancelledRef.current = false;

    if (!enabled || nickLiveId === null) {
      setSessions([]);
      return;
    }

    async function loop() {
      await fetchOnce();
      if (cancelledRef.current) return;
      timerRef.current = setTimeout(loop, POLL_INTERVAL_MS);
    }

    loop();

    return () => {
      cancelledRef.current = true;
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [enabled, nickLiveId, fetchOnce]);

  return { sessions, refresh };
}
```

- [ ] **Step 2: Build FE**

Run: `cd frontend && rtk npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
rtk git add frontend/src/hooks/useReplyLogSessions.ts
rtk git commit -m "feat(fe): useReplyLogSessions hook"
```

---

## Task 9: Frontend hook — `useReplyLogs` nhận `sessionId`

**Files:**
- Modify: `frontend/src/hooks/useReplyLogs.ts`

- [ ] **Step 1: Đọc file**

Run: `Read frontend/src/hooks/useReplyLogs.ts`

- [ ] **Step 2: Mở rộng signature và fetchOnce**

Sửa đoạn signature + fetchOnce:

```typescript
export function useReplyLogs(
  nickLiveId: number | null,
  enabled: boolean,
  sessionId: number | null = null
): UseReplyLogsResult {
  const [logs, setLogs] = useState<ReplyLog[]>([]);
  const [stats, setStats] = useState<ReplyLogStats | null>(null);
  const [index, setIndex] = useState<ReplyLogIndex>(() => ({
    byCommentKey: new Map(),
    byGuest: new Map(),
  }));

  const cancelledRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchOnce = useCallback(async () => {
    if (nickLiveId === null) return;
    try {
      const [logList, statResp] = await Promise.all([
        listReplyLogs({
          nick_live_id: nickLiveId,
          session_id: sessionId ?? undefined,
          limit: LOG_LIMIT,
        }),
        getReplyLogStats(nickLiveId),
      ]);
      if (cancelledRef.current) return;
      setLogs(logList);
      setStats(statResp);
      setIndex(buildIndex(logList));
    } catch {
      // Silent — polling will retry
    }
  }, [nickLiveId, sessionId]);
```

Và sửa effect deps:

```typescript
  }, [enabled, nickLiveId, sessionId, fetchOnce]);
```

- [ ] **Step 3: Build FE**

Run: `cd frontend && rtk npx tsc --noEmit`
Expected: PASS. Note: call site hiện tại trong `LiveScan.tsx` truyền 2 arg — default `sessionId = null` đảm bảo backward-compat, không break.

- [ ] **Step 4: Commit**

```bash
rtk git add frontend/src/hooks/useReplyLogs.ts
rtk git commit -m "feat(fe): useReplyLogs nhận sessionId filter"
```

---

## Task 10: Frontend UI — dropdown session + nút Clear trong Reply Logs modal

**Files:**
- Modify: `frontend/src/pages/LiveScan.tsx` (khu vực import + modal ~line 636-648)

- [ ] **Step 1: Đọc `LiveScan.tsx` khu vực modal**

Run: `Read frontend/src/pages/LiveScan.tsx offset=630 limit=40`
Ghi lại JSX hiện tại của modal.

- [ ] **Step 2: Thêm import**

Ở block import đầu file `LiveScan.tsx`:

```typescript
import { DeleteOutlined } from "@ant-design/icons";
import { Popconfirm, Select, Space, message } from "antd";
import { useReplyLogSessions } from "../hooks/useReplyLogSessions";
import { deleteReplyLogSession, type ReplyLogSession } from "../api/replyLogs";
```

(Nếu `Space`, `message`, `Popconfirm`, `Select` đã import từ `antd` — merge chung, không dup.)

- [ ] **Step 3: Thêm state + hook trong component**

Sau dòng `const [replyLogsModalOpen, setReplyLogsModalOpen] = useState(false);`:

```typescript
const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null);
const { sessions: replyLogSessions, refresh: refreshSessions } =
  useReplyLogSessions(selectedId, replyLogsModalOpen);
```

Sửa dòng `const { logs: replyLogs, ... } = useReplyLogs(selectedId, isScanning);` thành:

```typescript
const { logs: replyLogs, stats: replyStats, index: replyLogIndex, refresh: refreshReplyLogs } =
  useReplyLogs(selectedId, isScanning || replyLogsModalOpen, replyLogsModalOpen ? selectedSessionId : null);
```

Thêm effect auto-select session mới nhất khi sessions được load:

```typescript
useEffect(() => {
  if (!replyLogsModalOpen) return;
  if (replyLogSessions.length === 0) {
    setSelectedSessionId(null);
    return;
  }
  // Nếu selected hiện tại không còn trong list → pick newest
  if (
    selectedSessionId === null ||
    !replyLogSessions.some((s) => s.session_id === selectedSessionId)
  ) {
    setSelectedSessionId(replyLogSessions[0].session_id);
  }
}, [replyLogsModalOpen, replyLogSessions, selectedSessionId]);
```

Handler clear:

```typescript
const handleClearSession = useCallback(async () => {
  if (selectedId === null || selectedSessionId === null) return;
  try {
    const { deleted } = await deleteReplyLogSession(selectedId, selectedSessionId);
    message.success(`Đã xóa ${deleted} log của session ${selectedSessionId}`);
    refreshSessions();
    refreshReplyLogs();
  } catch {
    message.error("Không xóa được session log");
  }
}, [selectedId, selectedSessionId, refreshSessions, refreshReplyLogs]);
```

(Import `useCallback`, `useEffect` nếu chưa có.)

- [ ] **Step 4: Sửa JSX của Reply Logs modal**

Thay khối modal hiện tại:

```tsx
<Modal
  title="Tất cả Reply Logs"
  open={replyLogsModalOpen}
  onCancel={() => setReplyLogsModalOpen(false)}
  footer={null}
  width={900}
>
  <Space style={{ marginBottom: 12 }} wrap>
    <Select
      style={{ minWidth: 360 }}
      value={selectedSessionId}
      placeholder="Chọn session"
      onChange={(v) => setSelectedSessionId(v)}
      options={replyLogSessions.map((s: ReplyLogSession) => ({
        value: s.session_id,
        label: `Session #${s.session_id} · ${new Date(s.first_at).toLocaleTimeString()}–${new Date(s.last_at).toLocaleTimeString()} · ${s.count} reply`,
      }))}
      disabled={replyLogSessions.length === 0}
    />
    <Popconfirm
      title="Xóa toàn bộ log của session này?"
      description="Hành động không thể hoàn tác."
      okText="Xóa"
      cancelText="Hủy"
      onConfirm={handleClearSession}
      disabled={selectedSessionId === null}
    >
      <Button
        danger
        icon={<DeleteOutlined />}
        disabled={selectedSessionId === null}
      >
        Clear session này
      </Button>
    </Popconfirm>
  </Space>

  <div style={{ maxHeight: 600, overflowY: "auto" }}>
    {replyLogs.length === 0 ? (
      <Text type="secondary">Chưa có reply log nào</Text>
    ) : (
      replyLogs.map((log) => <ReplyLogRow key={log.id} log={log} />)
    )}
  </div>
</Modal>
```

(Giữ `<div style={{maxHeight ...}}>` tương tự layout hiện tại — nếu hiện tại dùng `Space direction="vertical"` thì dùng lại cho đồng bộ. Đọc Step 1 ghi lại.)

- [ ] **Step 5: Build FE**

Run: `cd frontend && rtk npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Manual smoke test**

Start BE + FE. Login → vào nick đang live → click "Tất cả Reply Logs":
- Dropdown hiện danh sách session, mới nhất trên cùng, có count.
- Chọn session cũ → log filter đúng.
- Click Clear → confirm → log của session đó biến mất khỏi list sessions + logs.
- Khi không có session nào → dropdown disabled, Clear disabled.

- [ ] **Step 7: Commit**

```bash
rtk git add frontend/src/pages/LiveScan.tsx
rtk git commit -m "feat(fe): reply log modal có dropdown session + Clear"
```

---

## Task 11: Self-check + cập nhật GitNexus index

- [ ] **Step 1: Run full backend test**

Run: `cd backend && rtk pytest`
Expected: all PASS.

- [ ] **Step 2: Run frontend typecheck**

Run: `cd frontend && rtk npx tsc --noEmit`
Expected: 0 errors.

- [ ] **Step 3: `gitnexus_detect_changes` scope check**

Run MCP tool `mcp__gitnexus__detect_changes({scope: "all"})`.
Expected: chỉ các file trong File Structure ở đầu plan xuất hiện.

- [ ] **Step 4: Refresh index**

Run: `rtk npx gitnexus analyze` (thêm `--embeddings` nếu `.gitnexus/meta.json` có `stats.embeddings > 0`).

- [ ] **Step 5: Tóm tắt thay đổi cho user**

Báo cáo: endpoint mới + retention + UI thay đổi.

---

## Self-Review Checklist

**Spec coverage:**
- ✅ GET `/api/reply-logs/sessions` → Task 2
- ✅ Filter `session_id` trong GET `/api/reply-logs` → Task 3
- ✅ DELETE `/api/reply-logs` + ownership 404 → Task 4
- ✅ Retention 3 ngày → Task 5
- ✅ `ReplyLogSessionSummary` schema → Task 1
- ✅ FE `listReplyLogSessions`, `deleteReplyLogSession` → Task 7
- ✅ FE `useReplyLogSessions` → Task 8
- ✅ FE `useReplyLogs` nhận `sessionId` → Task 9
- ✅ Modal dropdown + Clear → Task 10
- ✅ GitNexus impact verification → Task 11

**Placeholder scan:** không có "TBD/TODO/similar to". Tất cả code block concrete.

**Type consistency:**
- `ReplyLogSession` (FE) ↔ `ReplyLogSessionSummary` (BE response_model) → JSON shape khớp (`session_id`, `first_at`, `last_at`, `count`).
- `listReplyLogSessions(nickLiveId)` consistent khắp Task 7, 8, 10.
- `deleteReplyLogSession(nickLiveId, sessionId)` signature consistent Task 7, 10.
- `useReplyLogs(nickLiveId, enabled, sessionId?)` — default `null` ⇒ backward-compat (Task 9 với Task 10 call-site).
