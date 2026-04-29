# Admin Cross-User Live View — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho admin xem và thao tác đầy đủ trên live của bất kỳ user nào thông qua query param `as_user_id`.

**Architecture:** Thêm 1 FastAPI dependency `resolve_user_context` đọc query param `as_user_id`. Quét các router thuộc trang LiveScan thay `Depends(get_current_user)` bằng dep mới và đổi `current_user.id` → `ctx_user.id`. Frontend thêm zustand store `viewAsStore`, axios interceptor tự gắn param vào request nick-lives/reply-logs/settings/knowledge, dropdown chọn user trong `LiveScan.tsx`. Không migration DB, không service nền nào đổi (chúng key theo `nick_live_id` và lưu sẵn `user_id` của owner thật → log ghi như chính chủ).

**Tech Stack:** Python/FastAPI/SQLAlchemy/pytest (backend), React/TypeScript/Zustand/Ant Design/axios (frontend).

**Spec:** `docs/superpowers/specs/2026-04-29-admin-cross-user-live-view-design.md`.

---

## File Structure

**Backend — Create:**
- `backend/tests/test_nick_live_admin_view.py` — integration tests cho cơ chế `as_user_id`.
- `backend/tests/test_resolve_user_context.py` — unit tests cho dep mới.

**Backend — Modify:**
- `backend/app/dependencies.py` — thêm `resolve_user_context`.
- `backend/app/routers/nick_live.py` — toàn bộ endpoint dùng dep mới.
- `backend/app/routers/knowledge.py` — toàn bộ endpoint dùng dep mới.
- `backend/app/routers/reply_logs.py` — toàn bộ endpoint dùng dep mới.
- `backend/app/routers/settings.py` — toàn bộ endpoint dùng dep mới (settings này là per-user, không phải system keys).

**Backend — Không sửa:**
- `admin.py`, `auth.py`, `seeding.py`, `seeding_proxy.py`, `health.py`.

**Frontend — Create:**
- `frontend/src/stores/viewAsStore.ts` — zustand store giữ `viewAsUserId`.
- `frontend/src/components/livescan/ViewAsUserSelect.tsx` — dropdown + banner.

**Frontend — Modify:**
- `frontend/src/api/client.ts` — thêm interceptor request gắn `as_user_id`; mở rộng `withTokenQuery` → `withAuthQuery` để append cả `token` và `as_user_id` (cho SSE).
- `frontend/src/stores/liveScanStore.ts` — đổi `withTokenQuery` → `withAuthQuery` ở `openSSE`.
- `frontend/src/pages/LiveScan.tsx` — render `ViewAsUserSelect` cho admin, reset state khi `viewAsUserId` đổi.

---

## Task 1: Backend — `resolve_user_context` dependency

**Files:**
- Modify: `backend/app/dependencies.py`
- Create: `backend/tests/test_resolve_user_context.py`

- [ ] **Step 1.1: Write failing tests for `resolve_user_context`**

Create `backend/tests/test_resolve_user_context.py`:

```python
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.dependencies import resolve_user_context
from app.models.user import User
from app.services.auth import hash_password


USERNAMES = ["ruc_admin", "ruc_alice", "ruc_bob"]


@pytest.fixture(autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.add(User(username="ruc_admin", password_hash=hash_password("pw12345678"),
                    role="admin", max_nicks=None))
        db.add(User(username="ruc_alice", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=3))
        db.add(User(username="ruc_bob", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=3))
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.commit()


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/probe")
    def probe(ctx: User = Depends(resolve_user_context)):
        return {"id": ctx.id, "username": ctx.username}

    return app


def _login(client: TestClient, u: str) -> str:
    # Use the real login endpoint of the main app for token issuance.
    from app.main import app as main_app
    main_client = TestClient(main_app)
    return main_client.post(
        "/api/auth/login", json={"username": u, "password": "pw12345678"}
    ).json()["access_token"]


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _uid(username: str) -> int:
    with SessionLocal() as db:
        return db.query(User).filter_by(username=username).first().id


def test_no_param_returns_caller():
    app = _build_app()
    client = TestClient(app)
    tok = _login(client, "ruc_alice")
    r = client.get("/probe", headers=_hdr(tok))
    assert r.status_code == 200
    assert r.json()["username"] == "ruc_alice"


def test_self_param_returns_caller():
    app = _build_app()
    client = TestClient(app)
    tok = _login(client, "ruc_alice")
    r = client.get(f"/probe?as_user_id={_uid('ruc_alice')}", headers=_hdr(tok))
    assert r.status_code == 200
    assert r.json()["username"] == "ruc_alice"


def test_non_admin_with_other_id_forbidden():
    app = _build_app()
    client = TestClient(app)
    tok = _login(client, "ruc_alice")
    r = client.get(f"/probe?as_user_id={_uid('ruc_bob')}", headers=_hdr(tok))
    assert r.status_code == 403
    assert r.json()["detail"] == "Admin only"


def test_admin_with_other_id_returns_target():
    app = _build_app()
    client = TestClient(app)
    tok = _login(client, "ruc_admin")
    r = client.get(f"/probe?as_user_id={_uid('ruc_bob')}", headers=_hdr(tok))
    assert r.status_code == 200
    assert r.json()["username"] == "ruc_bob"


def test_admin_with_unknown_id_404():
    app = _build_app()
    client = TestClient(app)
    tok = _login(client, "ruc_admin")
    r = client.get("/probe?as_user_id=999999", headers=_hdr(tok))
    assert r.status_code == 404
    assert r.json()["detail"] == "Target user not found"
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `cd backend && rtk pytest tests/test_resolve_user_context.py -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_user_context'`.

- [ ] **Step 1.3: Implement `resolve_user_context`**

Edit `backend/app/dependencies.py`. Append at the bottom of the file:

```python
def resolve_user_context(
    as_user_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Return the user whose context the request operates in.

    - ``as_user_id`` omitted or equal to caller → caller (back-compat).
    - Non-admin caller passing a different id → 403.
    - Admin caller passing a non-existent id → 404.
    - Admin caller passing a valid id → that user.
    """
    if as_user_id is None or as_user_id == user.id:
        return user
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    target = db.get(User, as_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target user not found")
    return target
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `cd backend && rtk pytest tests/test_resolve_user_context.py -v`
Expected: 5 passed.

- [ ] **Step 1.5: Commit**

```bash
rtk git add backend/app/dependencies.py backend/tests/test_resolve_user_context.py
rtk git commit -m "feat(deps): add resolve_user_context for admin cross-user context"
```

---

## Task 2: Backend — Apply dep to `nick_live.py`

**Files:**
- Modify: `backend/app/routers/nick_live.py`
- Create: `backend/tests/test_nick_live_admin_view.py`

- [ ] **Step 2.1: Write failing integration tests**

Create `backend/tests/test_nick_live_admin_view.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.nick_live import NickLive
from app.models.user import User
from app.services.auth import hash_password


USERNAMES = ["nlav_admin", "nlav_alice", "nlav_bob"]


@pytest.fixture(autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.query(NickLive).filter(NickLive.name.like("nlav_%")).delete()
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.add(User(username="nlav_admin", password_hash=hash_password("pw12345678"),
                    role="admin", max_nicks=None))
        db.add(User(username="nlav_alice", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=5))
        db.add(User(username="nlav_bob", password_hash=hash_password("pw12345678"),
                    role="user", max_nicks=5))
        db.commit()

        bob_id = db.query(User).filter_by(username="nlav_bob").first().id
        db.add(NickLive(user_id=bob_id, name="nlav_bob_nick", shopee_user_id=111,
                        cookies="cookie-bob"))
        alice_id = db.query(User).filter_by(username="nlav_alice").first().id
        db.add(NickLive(user_id=alice_id, name="nlav_alice_nick", shopee_user_id=222,
                        cookies="cookie-alice"))
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(NickLive).filter(NickLive.name.like("nlav_%")).delete()
        db.query(User).filter(User.username.in_(USERNAMES)).delete()
        db.commit()


client = TestClient(app)


def _login(u: str) -> str:
    return client.post(
        "/api/auth/login", json={"username": u, "password": "pw12345678"}
    ).json()["access_token"]


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _uid(username: str) -> int:
    with SessionLocal() as db:
        return db.query(User).filter_by(username=username).first().id


def _bob_nick_id() -> int:
    with SessionLocal() as db:
        return db.query(NickLive).filter_by(name="nlav_bob_nick").first().id


def test_admin_lists_target_user_nicks():
    tok = _login("nlav_admin")
    r = client.get(
        f"/api/nick-lives?as_user_id={_uid('nlav_bob')}", headers=_hdr(tok)
    )
    assert r.status_code == 200
    names = [n["name"] for n in r.json()]
    assert names == ["nlav_bob_nick"]


def test_non_admin_with_other_as_user_id_forbidden():
    tok = _login("nlav_alice")
    r = client.get(
        f"/api/nick-lives?as_user_id={_uid('nlav_bob')}", headers=_hdr(tok)
    )
    assert r.status_code == 403


def test_admin_target_user_not_found():
    tok = _login("nlav_admin")
    r = client.get("/api/nick-lives?as_user_id=999999", headers=_hdr(tok))
    assert r.status_code == 404


def test_admin_no_param_sees_own_nicks_only():
    tok = _login("nlav_admin")
    r = client.get("/api/nick-lives", headers=_hdr(tok))
    assert r.status_code == 200
    # Admin owns no nicks in this fixture.
    assert r.json() == []


def test_admin_can_read_other_user_nick_cookies():
    tok = _login("nlav_admin")
    nick_id = _bob_nick_id()
    r = client.get(
        f"/api/nick-lives/{nick_id}/cookies?as_user_id={_uid('nlav_bob')}",
        headers=_hdr(tok),
    )
    assert r.status_code == 200
    assert r.json()["cookies"] == "cookie-bob"


def test_non_admin_cannot_access_other_user_nick():
    tok = _login("nlav_alice")
    nick_id = _bob_nick_id()
    # Without as_user_id: standard ownership check returns 404.
    r = client.get(f"/api/nick-lives/{nick_id}/cookies", headers=_hdr(tok))
    assert r.status_code == 404


def test_admin_get_scan_status_for_other_user():
    tok = _login("nlav_admin")
    nick_id = _bob_nick_id()
    r = client.get(
        f"/api/nick-lives/{nick_id}/scan/status?as_user_id={_uid('nlav_bob')}",
        headers=_hdr(tok),
    )
    assert r.status_code == 200
    assert "is_scanning" in r.json()
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `cd backend && rtk pytest tests/test_nick_live_admin_view.py -v`
Expected: FAIL — admin gets 404 because router still filters by `current_user.id`.

- [ ] **Step 2.3: Refactor `nick_live.py`**

Edit `backend/app/routers/nick_live.py`:

A. Update import line near other deps:

```python
from app.dependencies import get_current_user, resolve_user_context
```

B. **Replace every** function-parameter occurrence in this file:

```
current_user: User = Depends(get_current_user)
```

with:

```
ctx_user: User = Depends(resolve_user_context)
```

C. **Replace every** body occurrence of `current_user.id` with `ctx_user.id` and `current_user.max_nicks` with `ctx_user.max_nicks`. Specifically the patterns to swap:

- `current_user.id` → `ctx_user.id` (occurs in ~30 places).
- `current_user.max_nicks` → `ctx_user.max_nicks` (in `create_nick_live`).
- `_owned_nick_or_404(db, nick_live_id, current_user.id)` → `_owned_nick_or_404(db, nick_live_id, ctx_user.id)`.
- Calls passing user_id to services (e.g. `SettingsService(db, user_id=current_user.id)`) → `SettingsService(db, user_id=ctx_user.id)`.

Do **not** change `_owned_nick_or_404`'s signature — it already takes `user_id: int` and is the right abstraction.

D. Sanity grep before committing:

Run: `rtk grep -n "current_user" backend/app/routers/nick_live.py`
Expected: zero matches.

- [ ] **Step 2.4: Run new tests + regression**

Run: `cd backend && rtk pytest tests/test_nick_live_admin_view.py tests/test_nick_live_scan_stats.py tests/test_nick_live_sessions_batch.py tests/test_quota.py tests/test_user_isolation.py -v`
Expected: ALL passed (new file 7 passed, regression files unchanged behavior).

- [ ] **Step 2.5: Commit**

```bash
rtk git add backend/app/routers/nick_live.py backend/tests/test_nick_live_admin_view.py
rtk git commit -m "feat(nick-live): wire admin cross-user context via as_user_id"
```

---

## Task 3: Backend — Apply dep to `knowledge.py`

**Files:**
- Modify: `backend/app/routers/knowledge.py`

- [ ] **Step 3.1: Refactor `knowledge.py`**

Edit `backend/app/routers/knowledge.py`:

A. Update import:

```python
from app.dependencies import get_current_user, resolve_user_context
```

B. Update helper to accept user_id directly (decoupling from `current_user`):

Replace the existing helper:

```python
def _require_nick_ownership(nick_live_id: int, current_user: User, db: Session) -> NickLive:
    nick = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == current_user.id
    ).first()
    if not nick:
        raise HTTPException(status_code=404, detail="Nick not found")
    return nick
```

with:

```python
def _require_nick_ownership(nick_live_id: int, user_id: int, db: Session) -> NickLive:
    nick = db.query(NickLive).filter(
        NickLive.id == nick_live_id, NickLive.user_id == user_id
    ).first()
    if not nick:
        raise HTTPException(status_code=404, detail="Nick not found")
    return nick
```

C. In every endpoint of this file, swap:

- `current_user: User = Depends(get_current_user)` → `ctx_user: User = Depends(resolve_user_context)`
- `_require_nick_ownership(nick_live_id, current_user, db)` → `_require_nick_ownership(nick_live_id, ctx_user.id, db)`
- Any other `current_user.id` reference → `ctx_user.id`.

D. Sanity grep:

Run: `rtk grep -n "current_user" backend/app/routers/knowledge.py`
Expected: zero matches.

- [ ] **Step 3.2: Add cross-user test for knowledge router**

Append to `backend/tests/test_nick_live_admin_view.py`:

```python
def test_admin_can_list_other_user_knowledge_products():
    tok = _login("nlav_admin")
    nick_id = _bob_nick_id()
    r = client.get(
        f"/api/nick-lives/{nick_id}/knowledge/products?as_user_id={_uid('nlav_bob')}",
        headers=_hdr(tok),
    )
    # Empty list is fine; the contract is "no 404 because admin context".
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_non_admin_cannot_list_other_user_knowledge_products():
    tok = _login("nlav_alice")
    nick_id = _bob_nick_id()
    r = client.get(
        f"/api/nick-lives/{nick_id}/knowledge/products?as_user_id={_uid('nlav_bob')}",
        headers=_hdr(tok),
    )
    assert r.status_code == 403
```

> Note: if `knowledge.py` does not have a `GET /products` endpoint, replace the URL with the actual list endpoint defined in that router. Confirm by reading `backend/app/routers/knowledge.py` first; the test must hit a real GET endpoint of the knowledge router. Adjust the path to whatever read endpoint exists (do not invent one).

- [ ] **Step 3.3: Run tests**

Run: `cd backend && rtk pytest tests/test_nick_live_admin_view.py -v`
Expected: ALL passed.

- [ ] **Step 3.4: Commit**

```bash
rtk git add backend/app/routers/knowledge.py backend/tests/test_nick_live_admin_view.py
rtk git commit -m "feat(knowledge): wire admin cross-user context via as_user_id"
```

---

## Task 4: Backend — Apply dep to `reply_logs.py`

**Files:**
- Modify: `backend/app/routers/reply_logs.py`

- [ ] **Step 4.1: Refactor `reply_logs.py`**

Edit `backend/app/routers/reply_logs.py`:

A. Update import:

```python
from app.dependencies import get_current_user, resolve_user_context
```

B. In every endpoint, swap parameter:

```
current_user: User = Depends(get_current_user)  →  ctx_user: User = Depends(resolve_user_context)
```

C. In every body, swap `current_user.id` → `ctx_user.id`. This affects:

- `_owned_nick_ids(current_user.id, db)` → `_owned_nick_ids(ctx_user.id, db)`
- The `db.query(NickLive.id).filter(... NickLive.user_id == current_user.id)` in `delete_reply_log_session` → `... == ctx_user.id`.

D. Sanity grep:

Run: `rtk grep -n "current_user" backend/app/routers/reply_logs.py`
Expected: zero matches.

- [ ] **Step 4.2: Add cross-user test**

Append to `backend/tests/test_nick_live_admin_view.py`:

```python
def test_admin_can_list_other_user_reply_logs():
    tok = _login("nlav_admin")
    r = client.get(
        f"/api/reply-logs?as_user_id={_uid('nlav_bob')}", headers=_hdr(tok)
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_non_admin_cannot_list_other_user_reply_logs():
    tok = _login("nlav_alice")
    r = client.get(
        f"/api/reply-logs?as_user_id={_uid('nlav_bob')}", headers=_hdr(tok)
    )
    assert r.status_code == 403
```

- [ ] **Step 4.3: Run tests + regression**

Run: `cd backend && rtk pytest tests/test_nick_live_admin_view.py tests/test_reply_logs_delete.py tests/test_reply_logs_sessions.py tests/test_reply_log_retention.py -v`
Expected: ALL passed.

- [ ] **Step 4.4: Commit**

```bash
rtk git add backend/app/routers/reply_logs.py backend/tests/test_nick_live_admin_view.py
rtk git commit -m "feat(reply-logs): wire admin cross-user context via as_user_id"
```

---

## Task 5: Backend — Apply dep to `settings.py`

**Files:**
- Modify: `backend/app/routers/settings.py`

- [ ] **Step 5.1: Refactor `settings.py`**

Edit `backend/app/routers/settings.py`:

A. Update import:

```python
from app.dependencies import get_current_user, resolve_user_context
```

B. In every endpoint of this file, swap parameter:

```
current_user: User = Depends(get_current_user)  →  ctx_user: User = Depends(resolve_user_context)
```

C. In every body, swap `current_user.id` → `ctx_user.id` and `current_user.ai_key_mode` → `ctx_user.ai_key_mode`. Specifically the `update_openai_config` block:

```python
if ctx_user.ai_key_mode == "system":
    raise HTTPException(
        status_code=403,
        detail="Tài khoản đang dùng system key; không thể tự cấu hình",
    )
svc = SettingsService(db, user_id=ctx_user.id)
```

This means: if admin acts on user B who is in "system" mode, admin cannot override B's OpenAI key — same behavior as B itself. Correct under full-parity transparency.

D. Sanity grep:

Run: `rtk grep -n "current_user" backend/app/routers/settings.py`
Expected: zero matches.

- [ ] **Step 5.2: Add cross-user test**

Append to `backend/tests/test_nick_live_admin_view.py`:

```python
def test_admin_can_read_other_user_reply_templates():
    tok = _login("nlav_admin")
    r = client.get(
        f"/api/settings/reply-templates?as_user_id={_uid('nlav_bob')}",
        headers=_hdr(tok),
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_non_admin_cannot_read_other_user_reply_templates():
    tok = _login("nlav_alice")
    r = client.get(
        f"/api/settings/reply-templates?as_user_id={_uid('nlav_bob')}",
        headers=_hdr(tok),
    )
    assert r.status_code == 403
```

- [ ] **Step 5.3: Run tests + regression**

Run: `cd backend && rtk pytest tests/test_nick_live_admin_view.py tests/test_settings_service.py tests/test_nick_settings_ai_mode.py -v`
Expected: ALL passed.

- [ ] **Step 5.4: Final backend regression**

Run: `cd backend && rtk pytest -q`
Expected: full suite green.

- [ ] **Step 5.5: Commit**

```bash
rtk git add backend/app/routers/settings.py backend/tests/test_nick_live_admin_view.py
rtk git commit -m "feat(settings): wire admin cross-user context via as_user_id"
```

---

## Task 6: Frontend — `viewAsStore` + axios interceptor + SSE helper

**Files:**
- Create: `frontend/src/stores/viewAsStore.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/stores/liveScanStore.ts`

- [ ] **Step 6.1: Create `viewAsStore.ts`**

Create `frontend/src/stores/viewAsStore.ts`:

```typescript
import { create } from "zustand";

interface ViewAsState {
  viewAsUserId: number | null;
  setViewAsUserId: (id: number | null) => void;
}

export const useViewAsStore = create<ViewAsState>((set) => ({
  viewAsUserId: null,
  setViewAsUserId: (id) => set({ viewAsUserId: id }),
}));

// Module-level mirror so non-React code (axios interceptors, SSE URL builder)
// can read the value synchronously without subscribing.
let _viewAsUserId: number | null = null;
useViewAsStore.subscribe((state) => {
  _viewAsUserId = state.viewAsUserId;
});

export function getViewAsUserId(): number | null {
  return _viewAsUserId;
}
```

- [ ] **Step 6.2: Update `frontend/src/api/client.ts`**

Replace the entire file with:

```typescript
import axios, { type InternalAxiosRequestConfig } from "axios";
import { getViewAsUserId } from "../stores/viewAsStore";

const apiClient = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

// Routes that participate in the cross-user (as_user_id) context.
// Keep this list in sync with backend routers using resolve_user_context.
const CROSS_USER_PREFIXES = [
  "/nick-lives",
  "/reply-logs",
  "/settings",
];

function shouldAttachAsUserId(url: string | undefined): boolean {
  if (!url) return false;
  const path = url.startsWith("/") ? url : `/${url}`;
  return CROSS_USER_PREFIXES.some((p) => path === p || path.startsWith(`${p}/`) || path.startsWith(`${p}?`));
}

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const raw = localStorage.getItem("auth");
  if (raw) {
    try {
      const { token } = JSON.parse(raw);
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    } catch {
      /* ignore */
    }
  }

  const asUserId = getViewAsUserId();
  if (asUserId !== null && shouldAttachAsUserId(config.url)) {
    config.params = { ...(config.params ?? {}), as_user_id: asUserId };
  }

  return config;
});

apiClient.interceptors.response.use(
  (r) => r,
  (error) => {
    const status = error.response?.status;
    const url = error.config?.url ?? "";
    if ((status === 401 || status === 403) && !url.includes("/auth/login")) {
      localStorage.removeItem("auth");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  },
);

/** Append `token` query param to a URL (for SSE / static <a> links). */
export function withTokenQuery(url: string): string {
  const raw = localStorage.getItem("auth");
  if (!raw) return url;
  try {
    const { token } = JSON.parse(raw);
    if (!token) return url;
    const sep = url.includes("?") ? "&" : "?";
    return `${url}${sep}token=${encodeURIComponent(token)}`;
  } catch {
    return url;
  }
}

/** Append both `token` and (if active) `as_user_id` query params. Use for SSE. */
export function withAuthQuery(url: string): string {
  let out = withTokenQuery(url);
  const asUserId = getViewAsUserId();
  if (asUserId !== null) {
    const sep = out.includes("?") ? "&" : "?";
    out = `${out}${sep}as_user_id=${asUserId}`;
  }
  return out;
}

export default apiClient;
```

- [ ] **Step 6.3: Update `liveScanStore.ts` SSE URL builder**

Edit `frontend/src/stores/liveScanStore.ts`:

A. Change the import line:

```typescript
import { withTokenQuery } from "../api/client";
```

to:

```typescript
import { withAuthQuery } from "../api/client";
```

B. In `openSSE`, change:

```typescript
const url = withTokenQuery(`/api/nick-lives/${nickId}/comments/stream`);
```

to:

```typescript
const url = withAuthQuery(`/api/nick-lives/${nickId}/comments/stream`);
```

- [ ] **Step 6.4: Type-check**

Run: `cd frontend && rtk pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 6.5: Commit**

```bash
rtk git add frontend/src/stores/viewAsStore.ts frontend/src/api/client.ts frontend/src/stores/liveScanStore.ts
rtk git commit -m "feat(fe): viewAsStore + axios interceptor for as_user_id"
```

---

## Task 7: Frontend — `ViewAsUserSelect` component + integrate in `LiveScan.tsx`

**Files:**
- Create: `frontend/src/components/livescan/ViewAsUserSelect.tsx`
- Modify: `frontend/src/pages/LiveScan.tsx`

- [ ] **Step 7.1: Create `ViewAsUserSelect.tsx`**

Create `frontend/src/components/livescan/ViewAsUserSelect.tsx`:

```typescript
import { useEffect, useState } from "react";
import { Alert, Button, Select, Space, Spin, message } from "antd";
import { useAuth } from "../../contexts/AuthContext";
import { useViewAsStore } from "../../stores/viewAsStore";
import { listUsers, type AdminUser } from "../../api/admin";

interface ViewAsUserSelectProps {
  onContextChange: () => void;
}

export default function ViewAsUserSelect({ onContextChange }: ViewAsUserSelectProps) {
  const { user } = useAuth();
  const viewAsUserId = useViewAsStore((s) => s.viewAsUserId);
  const setViewAsUserId = useViewAsStore((s) => s.setViewAsUserId);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);

  const isAdmin = user?.role === "admin";

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    setLoading(true);
    listUsers()
      .then((data) => {
        if (!cancelled) setUsers(data);
      })
      .catch(() => {
        if (!cancelled) message.error("Không tải được danh sách user");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isAdmin]);

  if (!isAdmin || !user) return null;

  const handleChange = (value: number | null) => {
    const next = value === user.id ? null : value;
    setViewAsUserId(next);
    onContextChange();
  };

  const targetUsername =
    viewAsUserId === null
      ? user.username
      : users.find((u) => u.id === viewAsUserId)?.username ?? `user#${viewAsUserId}`;

  return (
    <Space direction="vertical" style={{ width: "100%", marginBottom: 12 }}>
      <Space wrap>
        <span>Đang xem live của:</span>
        <Select
          style={{ minWidth: 240 }}
          value={viewAsUserId ?? user.id}
          onChange={handleChange}
          loading={loading}
          notFoundContent={loading ? <Spin size="small" /> : null}
          options={[
            { value: user.id, label: `${user.username} (chính tôi)` },
            ...users
              .filter((u) => u.id !== user.id)
              .map((u) => ({
                value: u.id,
                label: `${u.username} (${u.nick_count} nicks)`,
              })),
          ]}
        />
        {viewAsUserId !== null && (
          <Button onClick={() => handleChange(null)}>← Về live của tôi</Button>
        )}
      </Space>
      {viewAsUserId !== null && (
        <Alert
          type="warning"
          showIcon
          message={`Bạn đang xem live của ${targetUsername} với quyền admin. Mọi thao tác sẽ được ghi như do ${targetUsername} thực hiện.`}
        />
      )}
    </Space>
  );
}
```

- [ ] **Step 7.2: Integrate in `LiveScan.tsx`**

Edit `frontend/src/pages/LiveScan.tsx`:

A. Add imports near the existing imports:

```typescript
import ViewAsUserSelect from "../components/livescan/ViewAsUserSelect";
import { useViewAsStore } from "../stores/viewAsStore";
import { useLiveScanStore } from "../stores/liveScanStore";
```

(Note: `useLiveScanStore` is already imported — keep the existing single import.)

B. Inside `LiveScan` component, add this block right after the existing `useLiveScanStore` hook calls and before `useNickLiveSessionsPoll`:

```typescript
const viewAsUserId = useViewAsStore((s) => s.viewAsUserId);

const handleContextChange = useCallback(() => {
  // Tear down all in-flight SSE / scanning state when switching user context.
  const { sseHandles, closeSSE } = useLiveScanStore.getState();
  Object.keys(sseHandles).forEach((id) => closeSSE(Number(id)));
  setNicks([]);
  setFocusNickId(null);
  setConfigNick(null);
  setEditCookieNick(null);
}, []);

// When viewAsUserId changes (including being cleared), reload nick list.
useEffect(() => {
  loadNicks();
  // loadNicks is stable; intentionally omit handleContextChange to avoid double-fire.
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [viewAsUserId]);
```

C. Render `ViewAsUserSelect` at the top of the JSX, immediately after `<div className="app-page-title-row">…</div>`:

```tsx
<div className="app-page-title-row">
  <Title level={3} style={{ margin: 0 }}>Quét Comment Live Shopee</Title>
</div>

<ViewAsUserSelect onContextChange={handleContextChange} />
```

- [ ] **Step 7.3: Type-check + lint**

Run: `cd frontend && rtk pnpm tsc --noEmit`
Expected: no errors.

Run: `cd frontend && rtk pnpm lint`
Expected: no errors.

- [ ] **Step 7.4: Manual smoke test**

1. Start backend + frontend (`docker compose up -d --build` or local dev).
2. Login as admin.
3. Navigate to `/live-scan`. Verify:
   - Dropdown shows above the table with self pre-selected.
   - List contains "<self> (chính tôi)" + each other user with nick count.
4. Pick another user (must have at least 1 nick live). Verify:
   - Banner cảnh báo hiện.
   - Bảng nick load đúng nick của user kia.
   - "← Về live của tôi" button visible.
5. Click a nick → `FocusFeedModal` mở; comments stream qua SSE chảy đúng (test trên 1 live đang chạy của user kia, hoặc chỉ verify connection mở mà không lỗi 404/403).
6. Bấm Start scan trên 1 nick (nếu user kia có active session) → status đổi → `scan-stats` poll OK.
7. Click "← Về live của tôi" → bảng load lại nick của admin, banner biến mất.
8. Logout, login as một non-admin → trang LiveScan **không** thấy dropdown / banner. Mọi hành vi y hệt cũ.

- [ ] **Step 7.5: Commit**

```bash
rtk git add frontend/src/components/livescan/ViewAsUserSelect.tsx frontend/src/pages/LiveScan.tsx
rtk git commit -m "feat(livescan): admin dropdown to view live of any user"
```

---

## Task 8: Final verification

- [ ] **Step 8.1: Full backend test suite**

Run: `cd backend && rtk pytest -q`
Expected: full suite green.

- [ ] **Step 8.2: Frontend build**

Run: `cd frontend && rtk pnpm build`
Expected: build succeeds with no type errors.

- [ ] **Step 8.3: Refresh GitNexus index**

Run: `rtk npx gitnexus analyze --embeddings`
Expected: index updated.

- [ ] **Step 8.4: Final commit (if any unstaged hunks remain)**

```bash
rtk git status
# If clean, skip. Otherwise stage and commit with a fix-up message.
```

---

## Self-Review (filled in by plan author)

**1. Spec coverage:**
- Spec §5.1 (param convention) → covered by Tasks 1–5 (helper + 4 router sweeps).
- Spec §5.2 (helper) → Task 1.
- Spec §5.3 (rules: 403 / 404 / passthrough) → Task 1 tests.
- Spec §5.4 (endpoint sweep: nick_live, knowledge, reply_logs, settings) → Tasks 2, 3, 4, 5 — one task per router.
- Spec §5.5 (background services unchanged) → no task needed (verified by passing existing tests in 5.4 / 8.1).
- Spec §5.6 (no migration) → no task; confirmed by absence of any migration file in the plan.
- Spec §6.1–6.4 (FE store, interceptor, dropdown, list-users endpoint) → Tasks 6 and 7.
- Spec §7.1 BE tests → covered piecemeal by Tasks 1, 2, 3, 4, 5 appending to `test_nick_live_admin_view.py`. SSE test is omitted from automated suite because it requires a running scanner; instead it's exercised in the manual smoke test (Step 7.4 #5).
- Spec §7.2 regression → Step 5.4 + Step 8.1.
- Spec §7.3 manual smoke test → Step 7.4.

**2. Placeholder scan:** No "TBD" / "TODO" / "implement later". The note in Step 3.2 about confirming the actual knowledge router list endpoint is concrete instruction (read file, pick the real endpoint), not a placeholder.

**3. Type / signature consistency:**
- `resolve_user_context(as_user_id, user, db) -> User` — defined Task 1, used in Tasks 2–5.
- `_require_nick_ownership(nick_live_id: int, user_id: int, db: Session) -> NickLive` — signature change defined in Task 3.1.B; only that file uses it (verified — no external callers because it starts with `_`).
- FE `useViewAsStore` API: `viewAsUserId`, `setViewAsUserId`, `getViewAsUserId()` — defined Task 6.1, used in Tasks 6.2 and 7.1.
- FE `withAuthQuery(url: string): string` — defined Task 6.2, used in Task 6.3.
- FE `ViewAsUserSelectProps.onContextChange: () => void` — defined Task 7.1, supplied in Task 7.2.B.
