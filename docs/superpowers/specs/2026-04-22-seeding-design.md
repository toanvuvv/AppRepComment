# Seeding Feature — Design Spec

**Date:** 2026-04-22
**Status:** Draft
**Author:** Claude + toanvuvv

---

## 1. Overview

Add a new **Seeding** tab (placed in the sidebar right after **LiveScan**) that lets a user create "clones" (dedicated Shopee accounts used only for commenting) and use them to post guest comments (**type 100**) into live sessions of their own registered host nicks.

Two modes:

- **Manual**: pick 1 clone + 1 live session → type a message → send once.
- **Auto**: pick N clones + 1 live session → a coordinated scheduler (one loop per session) randomly picks an eligible clone and a template from the pool, sending at random intervals between `min_interval_sec` and `max_interval_sec`.

**Credential model**: the Shopee message body for type 100 requires the live session host's `uuid` and `usersig`. These are already obtained via Relive and stored in `nick_live_settings.host_config` by the existing host-comment feature. The clone contributes only its `cookies` and identity. Therefore seeding is only available for live sessions whose host is a `nick_live` owned by the same user and already has `host_config` populated.

**Safety floor**: each clone is rate-limited to at most one comment every **10 seconds** across all sessions (hardcoded floor, enforced server-side).

**Out of scope (phase 1)**:

- Persisting scheduler state across backend restarts.
- Per-clone persona/templates.
- Manual broadcast-to-all-clones.
- Seeding into live sessions whose host is not on this system.
- Cross-user clone sharing.
- UI to tune the per-clone rate-limit floor.

---

## 2. Data Model

### 2.1 New table `seeding_clones`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `user_id` | INTEGER FK→users(id) ON DELETE CASCADE, indexed | ownership |
| `name` | VARCHAR(100) NOT NULL | from `payload.user.name` |
| `shopee_user_id` | BIGINT NOT NULL | from `payload.user.id` |
| `avatar` | VARCHAR(500) NULL | |
| `cookies` | TEXT (EncryptedString) NOT NULL | encrypted at rest |
| `proxy` | VARCHAR(255) NULL | format `http:host:port:user:pass` |
| `last_sent_at` | DATETIME NULL | for the 10s floor |
| `created_at` | DATETIME NOT NULL | |

No `shop_id` (clones do not own shops). No `host_config` (borrowed from the host nick at send time).

### 2.2 New table `seeding_comment_templates` (per-user global pool)

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `user_id` | INTEGER FK→users(id) ON DELETE CASCADE, indexed | |
| `content` | TEXT NOT NULL | the comment text |
| `enabled` | BOOLEAN NOT NULL DEFAULT true | disable without deleting |
| `created_at` | DATETIME NOT NULL | |

### 2.3 New table `seeding_log_sessions`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `user_id` | INTEGER FK→users(id), indexed | |
| `nick_live_id` | INTEGER FK→nick_lives(id) | host nick owning the live session |
| `shopee_session_id` | BIGINT NOT NULL | Shopee live session id |
| `mode` | VARCHAR(10) NOT NULL | `manual` or `auto` |
| `started_at` | DATETIME NOT NULL | |
| `stopped_at` | DATETIME NULL | NULL = running (auto only) |

**Reuse policy for `manual`**: before creating a new manual session log, look up an existing `(user_id, nick_live_id, shopee_session_id, mode='manual')` row whose `started_at` falls on the current UTC date; if found, reuse it. Otherwise create a new row.

### 2.4 New table `seeding_logs`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `seeding_log_session_id` | INTEGER FK→seeding_log_sessions(id) ON DELETE CASCADE, indexed | |
| `clone_id` | INTEGER FK→seeding_clones(id) | |
| `template_id` | INTEGER FK→seeding_comment_templates(id) NULL | NULL for manual |
| `content` | TEXT NOT NULL | the text actually sent |
| `status` | VARCHAR(20) NOT NULL | `success` / `failed` / `rate_limited` |
| `error` | TEXT NULL | |
| `sent_at` | DATETIME NOT NULL | |

### 2.5 Quota column

Add `users.max_clones INTEGER NULL` (parallel to `users.max_nicks`; NULL = unlimited).

### 2.6 Migration

`backend/migrations/add_seeding_tables.py`:

1. Create the four new tables above.
2. Add `users.max_clones`.
3. Create indexes on FK columns shown as "indexed".

---

## 3. Credential Resolution & Send Flow

### 3.1 Resolving credentials to send into session S

1. The frontend always passes `nick_live_id` together with `shopee_session_id` (the FE already knows both when the user picks a session from the host's session dropdown).
2. Backend validates that `nick_live_id` belongs to the current user.
3. Load `nick_live_settings.host_config` for that nick:
   - If NULL → return HTTP 400 `HOST_CONFIG_MISSING` with message: "Nick host chưa setup host config. Vào LiveScan → Nick config → Host → Get Credentials."
   - Else decrypt → `{ uuid, usersig }`.
4. Load `clone.cookies` (decrypt).
5. Build headers: reuse the same `_HOST_HEADERS` constant shape used by host-comment, plus:
   - `cookie`: the clone's cookies (decrypted).
   - `referer`: `https://live.shopee.vn/pc/live?session={shopee_session_id}`.
6. Build the type 100 body (§3.2).

To avoid tight coupling to `live_moderator.py`, `seeding_sender.py` defines its own private copy of the header dict. If these headers ever diverge from host-comment's, seeding is unaffected.

### 3.2 Type 100 body

```json
{
  "content": "{\"type\":100,\"content\":\"<comment text>\"}",
  "send_ts": <unix ms>,
  "usersig": "<host_config.usersig>",
  "uuid": "<host_config.uuid>"
}
```

No `pin` field (only the host may pin).

Endpoint: `POST https://live.shopee.vn/api/v1/session/{shopee_session_id}/message`.

### 3.3 `SeedingSender` (new service `backend/app/services/seeding_sender.py`)

Contract:

```
SeedingSender.send(
    clone_id: int,
    nick_live_id: int,
    shopee_session_id: int,
    content: str,
    template_id: int | None,
    mode: Literal["manual", "auto"],
    log_session_id: int,
) -> SeedingLog
```

Responsibilities:

1. **Floor check**: load `clone.last_sent_at`; if `now - last_sent_at < 10s`, do not POST. In `manual` mode, raise a typed exception that the router maps to HTTP 429 with `retry_after_sec`. In `auto` mode, write a `rate_limited` log and return it without raising.
2. Resolve credentials (§3.1).
3. Build body + headers. POST via the shared `shopee_limiter` (the existing global rate limiter used by host/moderator comments).
4. On success: update `clone.last_sent_at = now`; write `seeding_log` with `status=success`.
5. On HTTP error / Shopee API error: write `seeding_log` with `status=failed`, `error=<short message>`. In `manual` mode, raise so the router returns the error to the user. In `auto` mode, swallow and return.
6. **Retry**: reuse the same retry pattern `live_moderator.send_reply()` uses (same max retries, same backoff) — any 5xx or transient network error retries up to the configured limit before being classified as `failed`.

### 3.4 Floor enforcement details

- The 10s floor is a **global constant** in `seeding_sender.py` (e.g. `CLONE_FLOOR_SEC = 10`).
- The check uses `clone.last_sent_at` stored in `seeding_clones`. This persists across restarts.
- For the auto scheduler, when the chosen clone is floor-blocked, the scheduler logs `rate_limited` and continues to the next loop iteration (does not block the loop or retry immediately).

---

## 4. Auto Mode Scheduler

### 4.1 `SeedingScheduler` (new service `backend/app/services/seeding_scheduler.py`)

In-memory registry:

```
class SeedingScheduler:
    _tasks: dict[int, asyncio.Task]        # keyed by seeding_log_session_id
    _runs: dict[int, SeedingRunConfig]     # keyed by seeding_log_session_id

@dataclass(frozen=True)
class SeedingRunConfig:
    log_session_id: int
    user_id: int
    nick_live_id: int
    shopee_session_id: int
    clone_ids: tuple[int, ...]
    min_interval_sec: int
    max_interval_sec: int
```

### 4.2 Loop body (one task per `seeding_log_session_id`)

```
while not cancelled:
    sleep(random.uniform(min_interval_sec, max_interval_sec))

    templates = load enabled templates for user_id
    if not templates:
        log to seeding_logs with status=failed, error="no enabled templates"
        continue

    clones = load seeding_clones where id in clone_ids
    eligible = [c for c in clones if (now - c.last_sent_at) >= 10s or c.last_sent_at is None]

    if not eligible:
        pick any clone (first by id) and log status=rate_limited, template_id=None
        continue

    clone = random.choice(eligible)
    template = random.choice(templates)
    await SeedingSender.send(..., mode="auto", template_id=template.id, ...)
```

On cancel (stop): set `seeding_log_session.stopped_at = now`, remove from `_tasks` and `_runs`.

### 4.3 API endpoints (under `/api/seeding`)

| Method | Path | Body / Query | Purpose |
|---|---|---|---|
| POST | `/api/seeding/auto/start` | `{nick_live_id, shopee_session_id, clone_ids[], min_interval_sec, max_interval_sec}` | Create `seeding_log_session` (mode=`auto`), start task, return `{log_session_id}` |
| POST | `/api/seeding/auto/stop` | `{log_session_id}` | Cancel task, set `stopped_at` |
| GET | `/api/seeding/auto/status` | `?log_session_id=` | `{running, config}` |
| GET | `/api/seeding/auto/running` | — | List all runs currently running for this user |

### 4.4 Lifecycle & restart behaviour

Phase 1: scheduler state is in-memory only. On backend restart, running tasks are lost. The UI will reflect `stopped` state after restart, and the user must click Start again. (This mirrors the existing `auto_poster` behaviour.)

When a task is lost because the process crashed rather than being stopped cleanly, the corresponding `seeding_log_session.stopped_at` remains NULL — this is acceptable for phase 1; a future migration or cleanup job may zero these out on startup.

### 4.5 Start validation

- `clone_ids` non-empty and every id belongs to the current user.
- `nick_live_id` belongs to the current user and has `host_config` populated.
- `0 < min_interval_sec ≤ max_interval_sec`; `min_interval_sec >= 10`.
- Reject with HTTP 409 if a run already exists for `(user_id, shopee_session_id)` that has not been stopped — "Session đang seed, stop trước rồi start lại".
- `shopee_session_id` is trusted from the FE (the FE only shows sessions returned by Shopee's live session API); backend does not re-validate it.

---

## 5. Manual Mode & CRUD API

### 5.1 Manual send

| Method | Path | Body | Purpose |
|---|---|---|---|
| POST | `/api/seeding/manual/send` | `{clone_id, nick_live_id, shopee_session_id, content}` | Send one type-100 comment immediately |

Flow:

1. Validate `clone_id` and `nick_live_id` belong to the current user.
2. Find-or-create a manual `seeding_log_session` for `(user_id, nick_live_id, shopee_session_id, mode='manual', today UTC)` as defined in §2.3.
3. Call `SeedingSender.send(..., mode="manual", template_id=None, ...)`.
4. Return `{log_id, status}`. On floor violation return HTTP 429 `{retry_after_sec}`.

### 5.2 Clone CRUD

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/seeding/clones` | list clones of the current user |
| POST | `/api/seeding/clones` | create (body: `{user: {id, name, avatar?}, cookies, proxy?}` or flat form) |
| PATCH | `/api/seeding/clones/{id}` | update `proxy` / `cookies` / `name` |
| DELETE | `/api/seeding/clones/{id}` | delete; reject with HTTP 409 if the clone is in a running auto run |

Creation enforces `users.max_clones` quota in the same way nick creation enforces `max_nicks`. The request parser reuses the flat-or-nested pattern of `NickLiveCreate` so `{user: {id, name}, cookies}` works unchanged.

### 5.3 Template CRUD

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/seeding/templates` | list (of user) |
| POST | `/api/seeding/templates` | create (`{content, enabled?}`) |
| PATCH | `/api/seeding/templates/{id}` | edit content / toggle `enabled` |
| DELETE | `/api/seeding/templates/{id}` | delete |
| POST | `/api/seeding/templates/bulk` | body: `{lines: string[]}`; creates one template per non-empty line |

### 5.4 Log endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/seeding/log-sessions` | list log sessions; filters: `nick_live_id`, `mode`, `date_from`, `date_to` |
| GET | `/api/seeding/logs` | `?log_session_id=...&page=&page_size=`; paginated |

---

## 6. Frontend UI

### 6.1 Sidebar

Add a new menu item **"Seeding"** immediately after **"LiveScan"**. Route: `/seeding`.

### 6.2 Page layout

`frontend/src/pages/Seeding.tsx` is a container with 4 sub-tabs (+ one optional):

#### Sub-tab 1: Clones
- Table: `name`, `shopee_user_id`, `avatar`, `proxy`, `last_sent_at`, actions (Edit proxy, Update cookies, Delete).
- Button **"+ Add Clone"**: modal with a JSON paste area accepting `{user: {id, name, avatar?}, cookies, proxy?}` (or flat `{name, shopee_user_id, cookies, proxy?}`). Reuse the existing Nick Live parser component.
- Quota badge: `X / Y clones`.

#### Sub-tab 2: Templates
- List with inline edit (content, enabled toggle) and delete.
- **"Bulk import"** textarea: one line = one template.
- **"+ Add"** button for a single template.

#### Sub-tab 3: Manual Send
- Row 1: Host nick dropdown (user's `nick_lives` that have `host_config`) → live session dropdown (loaded from Shopee via the existing sessions API).
- Row 2: Clone dropdown.
- Row 3: content textarea + **"Gửi"** button.
- Below: a mini live-log of the last 10 sent comments with status (`success` / `failed` / `rate_limited` showing `retry_after_sec`).

#### Sub-tab 4: Auto Runner
- Start form:
  - Host nick + session (same as Manual).
  - Multi-select clones (checkbox list from the pool).
  - `min_interval_sec`, `max_interval_sec` (defaults 30 / 120; `min_interval_sec` floor is 10).
  - **"Start Auto"** button.
- "Running runs" panel: one row per active run, showing nick host, session id, clone ids, intervals, `started_at`, success/fail counters, and a **"Stop"** button.
- Clicking a run opens a drawer with the run's detail logs (reuse the `ReplyLogSession` pattern).

#### Sub-tab 5 (optional): Logs
- `seeding_log_sessions` table with filters (nick, mode, date range).
- Clicking a row opens the same drawer as Auto Runner.
- Can be merged into Sub-tab 4 if five tabs feel excessive — decision made during implementation.

### 6.3 New FE files

- `frontend/src/pages/Seeding.tsx`
- `frontend/src/components/seeding/ClonesTab.tsx`
- `frontend/src/components/seeding/TemplatesTab.tsx`
- `frontend/src/components/seeding/ManualSendTab.tsx`
- `frontend/src/components/seeding/AutoRunnerTab.tsx`
- `frontend/src/components/seeding/SeedingLogDrawer.tsx`
- `frontend/src/api/seeding.ts`
- `frontend/src/hooks/useSeedingClones.ts`
- `frontend/src/hooks/useSeedingTemplates.ts`
- `frontend/src/hooks/useSeedingRuns.ts`
- `frontend/src/hooks/useSeedingLogs.ts`

### 6.4 Modified FE files

- `frontend/src/App.tsx` — add `/seeding` route.
- Sidebar component — add the "Seeding" entry after "LiveScan".

---

## 7. File Change Summary

### New backend files

| File | Purpose |
|---|---|
| `backend/app/models/seeding.py` | ORM: `SeedingClone`, `SeedingCommentTemplate`, `SeedingLogSession`, `SeedingLog` |
| `backend/app/schemas/seeding.py` | Pydantic schemas for clone/template/run/log |
| `backend/app/services/seeding_sender.py` | `SeedingSender.send()` |
| `backend/app/services/seeding_scheduler.py` | `SeedingScheduler` — per-session async task pool |
| `backend/app/routers/seeding.py` | All `/api/seeding/*` endpoints |
| `backend/migrations/add_seeding_tables.py` | DB migration |

### Modified backend files

| File | Change |
|---|---|
| Backend entrypoint (e.g. `backend/app/main.py`) | Register the seeding router |
| `backend/app/models/user.py` | Add `max_clones: int \| None` |

### Frontend

See §6.3 (new) and §6.4 (modified).

---

## 8. Testing (phase 1 minimum)

- **Unit — `seeding_sender.send()`**: mock the Shopee POST and verify:
  - Body is exactly `{"content": "{\"type\":100,\"content\":\"<text>\"}", "send_ts", "usersig", "uuid"}` with `usersig`/`uuid` from the host nick's `host_config`.
  - Floor enforcement: two consecutive calls within 10s — second returns `rate_limited` in auto mode and raises in manual mode.
  - Retry behaviour on 5xx matches `live_moderator.send_reply`.
- **Unit — `seeding_scheduler`**: mock the sender and verify:
  - Random clone/template selection from the allowed pool.
  - Rate-limited clones are skipped and logged.
  - `stop` cancels the task and sets `stopped_at`.
- **Integration**: create clone → create templates → manual send → verify `seeding_logs` row exists with `status=success`, `template_id=NULL`, correct `log_session_id` (find-or-create).

---

## 9. Decisions Locked (from brainstorming)

| # | Decision |
|---|---|
| 1 | Clones live in a separate `seeding_clones` table (not reusing `nick_lives`). |
| 2 | Body type 100 uses the **host's** `uuid`/`usersig` (from `nick_live_settings.host_config`); clone only supplies cookies. |
| 3 | Clones are owned by a user (per-user pool), usable for any of the user's own host nicks. |
| 4 | Comment templates are a **per-user global pool** (no per-clone personas in phase 1). |
| 5 | Auto mode uses a **coordinated scheduler per session**; the same clone may appear in multiple concurrent session runs. |
| 6 | Manual mode sends from **one clone into one session** per click. |
| 7 | Clone creation input reuses the Nick Live JSON shape `{user: {id, name, …}, cookies}` plus optional `proxy`. |
| 8 | Auto run uses an **explicit list of clones** chosen at Start; no dynamic add/remove mid-run in phase 1. |
| 9 | Seeding is only allowed into live sessions whose host is a user-owned nick with `host_config` populated. |
| 10 | Seeding logs live in their own tables `seeding_log_sessions` / `seeding_logs` (not merged into `reply_logs`). |
| 11 | A **10-second hardcoded floor** applies to every clone globally across sessions. |
| 12 | Sidebar tab position: **immediately after LiveScan**. |
