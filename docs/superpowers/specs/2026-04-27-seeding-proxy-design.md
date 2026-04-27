# Seeding Proxy — Design Spec

**Date:** 2026-04-27
**Feature area:** Seeding
**Status:** Approved (pending implementation plan)

## Summary

Add per-system-user proxy management for the Seeding feature. Users can bulk-import proxies, CRUD them, and round-robin assign proxies to their clones. Proxies are wired into the seeding sender so type-100 comments are posted through the assigned proxy. UI lives entirely inside Seeding — a "Setting Proxy" modal accessible from the Clones tab toolbar.

## Goals

- Users (per system account) maintain their own proxy pool, isolated from other users.
- Bulk import proxies in `host:port:user:pass` format, one per line.
- Round-robin assignment: with N proxies and M clones, clone i gets proxy `i mod N`.
- Real proxy usage at send time (currently `clone.proxy` exists but is ignored by the sender).
- CRUD individual proxies; edits propagate to clones using the proxy.
- Optional toggle to enforce proxy usage (skip clones without proxy).

## Non-Goals (Phase 2)

- Proxy health check / test on import.
- Auto-disable dead proxies.
- Per-proxy stats (success rate, last_used).
- Sticky / pinned proxy on a specific clone (overrides round-robin).
- Sharing proxies across system users.

## Decisions Captured From Brainstorm

| # | Decision |
|---|---|
| 1 | Import format: `host:port:user:pass`, one proxy per line. |
| 2 | Scheme picked via dropdown in import modal (applies to whole batch); editable per-row afterwards. Supported schemes: `socks5`, `http`, `https`. |
| 3 | Round-robin assignment triggered by explicit "Gán xoay vòng" button. Checkbox "Chỉ gán cho clone chưa có proxy" preserves manually-set assignments. |
| 4 | New `seeding_proxies` table; `SeedingClone.proxy_id` FK with `ON DELETE SET NULL`. `clone.proxy` kept as cached URL string for sender. |
| 5 | When `clone.proxy` is NULL: per-user toggle `seeding.require_proxy` (default `false`). Off → send direct. On → skip and log `error='no_proxy'`. |
| 6 | "Setting Proxy" button placed in toolbar of the Clones tab, beside "Thêm clone". |

## Data Model

### New table `seeding_proxies`

| Column | Type | Notes |
|---|---|---|
| `id` | INT PK autoincrement | |
| `user_id` | INT FK `users.id` ON DELETE CASCADE | indexed |
| `scheme` | VARCHAR(10) | `'socks5'` \| `'http'` \| `'https'` |
| `host` | VARCHAR(255) | |
| `port` | INT | |
| `username` | VARCHAR(255) NULL | |
| `password` | EncryptedString NULL | encrypted at rest, like `clone.cookies` |
| `note` | VARCHAR(255) NULL | optional user note |
| `created_at` | DATETIME | UTC |

**Constraints:**
- `UNIQUE (user_id, scheme, host, port, username)` — dedupe imports.

### `SeedingClone` changes

- Add `proxy_id INT NULL`, FK `seeding_proxies.id` ON DELETE SET NULL, indexed.
- Keep existing `proxy: str | None` as the cached URL string consumed by `seeding_sender`. Format: `"{scheme}://{user}:{pass}@{host}:{port}"` (user/pass URL-encoded). Updated whenever assignment changes or the source proxy is edited/deleted.

### Setting

- Per-user toggle stored via existing `SettingsService`, key `seeding.require_proxy`, default `false`.

### Migration

- One Alembic revision: create `seeding_proxies`, add `proxy_id` column to `seeding_clones`. No data backfill needed; existing `clone.proxy` strings remain untouched.

## Backend

### New files

- `backend/app/models/seeding.py` — add `SeedingProxy` class; add `proxy_id` to `SeedingClone`.
- `backend/app/schemas/seeding_proxy.py` — Pydantic models: `ProxyCreate`, `ProxyUpdate`, `ProxyOut`, `ProxyImportRequest`, `ProxyImportResult`, `ProxyAssignRequest`, `ProxyAssignResult`, `RequireProxySetting`.
- `backend/app/services/seeding_proxy_service.py` — all business logic (see below).
- `backend/app/routers/seeding_proxy.py` — REST router.

### Service: `seeding_proxy_service.py`

- `parse_bulk(raw_text: str, scheme: str) -> tuple[list[ParsedProxy], list[ParseError]]`
  - Strip comments (lines starting with `#`) and blank lines.
  - Validate `host:port:user:pass`. Port must be 1–65535.
  - Returns parsed entries plus per-line errors with `{line, raw, reason}`.
- `import_bulk(user_id, scheme, raw_text) -> ProxyImportResult`
  - Inserts unique entries, dedupes against existing rows for the user via the UNIQUE constraint.
  - Returns `{created: int, skipped_duplicates: int, errors: list}`.
- `format_url(proxy: SeedingProxy) -> str`
  - Returns `"{scheme}://{quote(user)}:{quote(pass)}@{host}:{port}"` (URL-encoded credentials). If no auth, omits credentials.
- `assign_round_robin(user_id, only_unassigned: bool) -> ProxyAssignResult`
  - Loads proxies `ORDER BY id ASC`, clones `ORDER BY id ASC` (does not filter `auto_disabled`).
  - If `only_unassigned`: filters clones with `proxy_id IS NULL`.
  - Sets `clone.proxy_id = proxies[i % len(proxies)]` and `clone.proxy = format_url(...)`.
  - No-op when 0 proxies or 0 clones; returns `{assigned: 0, reason: "no_proxies"|"no_clones"|"all_assigned"}`.
- `update_proxy_cache_for_clones(proxy_id)` — called after edit; refreshes `clone.proxy` cache string for every clone using this proxy.
- `clear_proxy_cache_for_clones(proxy_id)` — called after delete; sets `clone.proxy_id = NULL` and `clone.proxy = NULL` for affected clones (handled by FK SET NULL + explicit cache clear in the same transaction).

### Router: `seeding_proxy.py`

Mounted at `/api/seeding/proxies`. All endpoints `Depends(current_user)` and use a `_owned_proxy(proxy_id, user)` helper analogous to `_owned_clone`.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/` | — | `list[ProxyOut]` (no password) |
| POST | `/` | `ProxyCreate` | `ProxyOut` |
| PATCH | `/{id}` | `ProxyUpdate` (partial) | `ProxyOut` — also refreshes cache on clones |
| DELETE | `/{id}` | — | `204` — clears cache on affected clones |
| POST | `/import` | `{scheme, raw_text}` | `ProxyImportResult` |
| POST | `/assign` | `{only_unassigned: bool}` | `ProxyAssignResult` |
| GET | `/setting` | — | `{require_proxy: bool}` |
| PUT | `/setting` | `{require_proxy: bool}` | `{require_proxy: bool}` |

`ProxyOut` exposes `id, scheme, host, port, username, note, created_at, used_by_count`. Password is never returned.

### Wiring proxy into `seeding_sender.py`

- Add `get_client_for_proxy(proxy_url: str | None) -> httpx.AsyncClient` to `app/services/http_client.py`. Internally caches one `AsyncClient` per distinct proxy URL (and one for `None` = direct, the existing client). Reuses the same headers/timeout config.
- In `SeedingSender.send`:
  1. After loading the clone, read `require_proxy` setting for `clone.user_id`.
  2. If `require_proxy and not clone.proxy`:
     - `manual` mode: raise `RuntimeError("no_proxy")` after writing `failed/no_proxy` log.
     - `auto` mode: write `failed/no_proxy` log, increment `consecutive_failures`, return.
  3. Otherwise, pass `clone.proxy` (or `None`) into `_post_with_retry`, which acquires the right client via `get_client_for_proxy`.
- `_post_with_retry` signature gains a `proxy_url: str | None` parameter.
- Existing rate-limiter, retry, and auto-disable logic unchanged.

### Tests (pytest)

- `backend/tests/test_seeding_proxy_service.py`
  - `parse_bulk`: valid lines, invalid (missing fields, bad port, blank, comment), trims whitespace.
  - `import_bulk`: dedupe via UNIQUE, error aggregation.
  - `format_url`: with/without auth, special-character encoding in password.
  - `assign_round_robin`: 1 proxy / N clones, 2 proxies / 3 clones, 0 proxies → no-op, `only_unassigned=True` skips already-assigned, idempotent on second call.
  - `update_proxy_cache_for_clones` and clear-on-delete behavior.
- `backend/tests/test_seeding_proxy_router.py`
  - CRUD happy path + permission isolation (user A cannot read/edit user B's proxy).
  - Import endpoint surfaces `created/skipped_duplicates/errors` correctly.
  - Setting endpoint round-trip.
- `backend/tests/test_seeding_sender.py` (additions)
  - Clone with proxy → mocked `httpx.AsyncClient` is acquired with the right proxy URL.
  - `require_proxy=True` and `clone.proxy=None` → log `failed/no_proxy`, no HTTP call. Manual raises, auto returns log row.
  - Direct send (no proxy, `require_proxy=False`) preserves current behavior.

Coverage target: 80%+ on the new service and router (project standard).

## Frontend

### New files

- `frontend/src/api/seedingProxy.ts` — typed API client for the 8 endpoints; types `SeedingProxy`, `ProxyImportPayload`, `ProxyAssignPayload`, `ProxyImportResult`, `ProxyAssignResult`, `RequireProxySetting`.
- `frontend/src/components/seeding/ProxySettingsModal.tsx` — modal owning the entire proxy management UI.
- `frontend/src/components/seeding/ProxyImportPanel.tsx` — sub-component: scheme dropdown + textarea + Import button; renders import result summary.
- `frontend/src/components/seeding/ProxyTable.tsx` — sub-component: list + inline edit + delete confirm.

### Changes to `frontend/src/components/seeding/ClonesTab.tsx`

- Add **"⚙ Setting Proxy"** button in the Clones toolbar, beside "Thêm clone".
- Click opens `ProxySettingsModal`.
- The clone list's "Proxy" column displays `scheme://host:port` derived from `proxy_id` (backend list-clones response is extended with a small `proxy: {scheme, host, port}` object so the frontend doesn't need a second fetch).

### Modal layout

```
┌────────────────────────────────────────────────────┐
│ Setting Proxy (Seeding)                       [X] │
├────────────────────────────────────────────────────┤
│ ☐ Bắt buộc dùng proxy (skip clone không có proxy) │
├────────────────────────────────────────────────────┤
│ ── Import hàng loạt ──                            │
│ Scheme: [socks5 ▾]                                │
│ ┌────────────────────────────────────────────┐    │
│ │ host:port:user:pass                        │    │
│ │ host:port:user:pass                        │    │
│ │ ...                                        │    │
│ └────────────────────────────────────────────┘    │
│ [Import]   → "Đã thêm 12, trùng 3, lỗi 1: …"     │
├────────────────────────────────────────────────────┤
│ ── Danh sách proxy (24) ──        [+ Thêm thủ công]│
│ ┌──────────────────────────────────────────────┐  │
│ │ socks5  proxyx3.ddns.net:4001  proxy   [✎][🗑]│  │
│ │ http    1.2.3.4:8080           admin   [✎][🗑]│  │
│ └──────────────────────────────────────────────┘  │
├────────────────────────────────────────────────────┤
│ ── Gán proxy cho clones ──                        │
│ ☑ Chỉ gán cho clone chưa có proxy                 │
│ [Gán xoay vòng]   → "Đã gán cho 8/12 clone"      │
└────────────────────────────────────────────────────┘
```

### UX details

- Password rendered as `••••••`; eye toggle to reveal (calls a separate `GET /api/seeding/proxies/{id}/reveal` endpoint that returns the decrypted password — added to backend; same auth gate). Fallback: do not surface a reveal endpoint at all and require password re-entry on edit. Pick one during planning; spec defaults to **the second option (no reveal endpoint)** for security simplicity.
- Delete confirm dialog warns "X clone đang dùng proxy này sẽ bị bỏ trống" (count from `used_by_count`).
- "Gán xoay vòng" disabled with tooltip when 0 proxies or 0 clones.
- After any mutation, refetch the clones list so the Proxy column updates.

### Frontend tests (vitest)

- `ProxyImportPanel`: renders error rows from import result.
- `ProxyTable`: delete confirm shows correct count, blocks delete on cancel.
- No new E2E browser tests required (modal is internal).

## Round-robin Semantics

- Sort: proxies `ORDER BY id ASC`, clones `ORDER BY id ASC` (no filter on `auto_disabled`).
- Assignment: `clones[i].proxy_id = proxies[i mod len(proxies)].id`.
- Idempotent: repeated calls with the same inputs produce the same assignment.
- Stability when adding a new proxy: existing assignments for older clone IDs remain on their original proxy; the new proxy participates in the cycle for clones at the tail end.

## Edge Cases

| Situation | Behavior |
|---|---|
| 0 proxies + assign | `{assigned: 0, reason: "no_proxies"}`; frontend toast warning. |
| 0 clones | `{assigned: 0, reason: "no_clones"}`. |
| `only_unassigned=True` and all clones already assigned | `{assigned: 0, reason: "all_assigned"}`. |
| Edit proxy host/port/credentials | Refresh `clone.proxy` cache for all clones using it (same transaction). |
| Delete proxy in use | FK SET NULL + explicit cache clear; affected clones revert to "no proxy". |
| Bad import line | Skip line, include in `errors[]`; do not abort batch. |
| Duplicate import line (existing in DB) | Skip silently, count in `skipped_duplicates`. |
| `require_proxy=True` and `clone.proxy=NULL` | Sender writes `failed/no_proxy` log. Manual mode raises `RuntimeError("no_proxy")`; auto mode returns the log row. |
| Proxy unreachable at send time | Existing retry runs; final failure logs as `request_failed` (or exception name). No auto-disable of the proxy in MVP. |

## Files Touched

**New:**
- `backend/alembic/versions/<rev>_add_seeding_proxies.py`
- `backend/app/schemas/seeding_proxy.py`
- `backend/app/services/seeding_proxy_service.py`
- `backend/app/routers/seeding_proxy.py`
- `backend/tests/test_seeding_proxy_service.py`
- `backend/tests/test_seeding_proxy_router.py`
- `frontend/src/api/seedingProxy.ts`
- `frontend/src/components/seeding/ProxySettingsModal.tsx`
- `frontend/src/components/seeding/ProxyImportPanel.tsx`
- `frontend/src/components/seeding/ProxyTable.tsx`
- `frontend/src/components/seeding/__tests__/ProxyImportPanel.test.tsx`
- `frontend/src/components/seeding/__tests__/ProxyTable.test.tsx`

**Modified:**
- `backend/app/models/seeding.py` — add `SeedingProxy`, add `proxy_id` to `SeedingClone`.
- `backend/app/services/http_client.py` — add `get_client_for_proxy(proxy_url)`.
- `backend/app/services/seeding_sender.py` — wire proxy into `_post_with_retry`, enforce `require_proxy`.
- `backend/app/routers/seeding.py` — extend list-clones response with `proxy` summary; mount new router.
- `backend/app/main.py` (or wherever routers register) — include `seeding_proxy.router`.
- `backend/tests/test_seeding_sender.py` — add proxy-path tests.
- `frontend/src/api/seeding.ts` — `SeedingClone` interface gains optional `proxy: {scheme, host, port} | null`.
- `frontend/src/components/seeding/ClonesTab.tsx` — toolbar button + Proxy column rendering.

## Open Questions Deferred to Implementation

- Reveal-password endpoint vs require-re-entry on edit. Spec defaults to require-re-entry; revisit during planning if UX feedback requires reveal.
- Whether to expose `used_by_count` via a separate aggregation query or join on each list call. Default: subquery in the GET list endpoint; revisit if perf shows up.
