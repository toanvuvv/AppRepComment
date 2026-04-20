# Multi-User Auth & Admin Management — Design

**Date:** 2026-04-20
**Status:** Draft (pending approval)

## Goal

Replace the single shared API key (`X-API-Key`) with a multi-user system:

- Login page with username/password.
- Admin role that can create users, reset passwords, lock/unlock, delete, and set per-user quota for max nick_lives.
- Each user manages their own Relive API + AI API settings, their own nick_lives, knowledge base, and reply logs.
- Admin is also a regular user (unlimited quota) — admin can run nicks too.

## Non-Goals

- No admin impersonation / view-other-users-data (v1).
- No email, password reset via email, 2FA, OAuth.
- No refresh tokens (JWT access-only, 8h TTL, re-login on expiry).
- No audit log of admin actions.

## Roles

| Role  | Capabilities |
|-------|--------------|
| admin | All user capabilities + `/admin/users` CRUD + unlimited `max_nicks` |
| user  | Login, change own password, manage own nicks/settings/knowledge, bounded by `max_nicks` quota |

Admin is a real user row with `role='admin'` and `max_nicks=NULL` (unlimited).

## Data Model

### New table `users`

| Column        | Type                | Notes                              |
|---------------|---------------------|------------------------------------|
| id            | int PK autoincrement|                                    |
| username      | varchar(50) unique  | 3–50 chars, `[a-zA-Z0-9_-]`        |
| password_hash | varchar(255)        | bcrypt, cost 12                    |
| role          | varchar(10)         | `'admin'` \| `'user'`              |
| max_nicks     | int NULL            | NULL = unlimited (admin)           |
| is_locked     | bool default false  |                                    |
| created_at    | datetime            |                                    |
| updated_at    | datetime            |                                    |

### Existing tables — add `user_id` FK

- `nick_lives`: `user_id int NOT NULL, FK users(id) ON DELETE CASCADE`, index.
- `settings`: `user_id int NOT NULL, FK users(id) ON DELETE CASCADE, UNIQUE (user_id)`. The current global-singleton semantics becomes per-user.
- `reply_logs`: `user_id int NOT NULL, FK users(id) ON DELETE CASCADE`, index.
- `knowledge_products`: `user_id int NOT NULL, FK users(id) ON DELETE CASCADE`, index.

### Seeding

On `lifespan()` startup:

1. Read `ADMIN_USERNAME` + `ADMIN_PASSWORD` from env.
2. If no user in DB → create admin (`role='admin'`, `max_nicks=NULL`).
3. Log warning once if env vars missing and no admin exists (block startup in prod mode).

## Backend

### New modules

- `app/models/user.py` — `User` SQLAlchemy model.
- `app/schemas/user.py` — Pydantic: `LoginRequest`, `LoginResponse`, `ChangePasswordRequest`, `UserCreate`, `UserUpdate`, `UserOut`.
- `app/services/auth.py` — bcrypt hash/verify, JWT encode/decode, password policy.
- `app/routers/auth.py` — login, me, change-password.
- `app/routers/admin.py` — users CRUD.
- `app/dependencies.py` — add `get_current_user()`, `require_admin()`. Remove `require_api_key` after migration.

### JWT

- Library: `python-jose[cryptography]`.
- Algorithm: HS256.
- Secret: `JWT_SECRET` env (required in prod, dev default with warning).
- TTL: 8 hours.
- Payload: `{sub: user_id, username, role, exp, iat}`.
- Extraction: `Authorization: Bearer <token>` header OR `?token=<token>` query (for SSE).

### Endpoints

Public:

- `POST /api/auth/login` — `{username, password}` → `{access_token, token_type:"bearer", user: UserOut}`. 401 if invalid creds; 403 if `is_locked`.

Authenticated (any user):

- `GET /api/auth/me` → current `UserOut`.
- `POST /api/auth/change-password` — `{old_password, new_password}` → 204. Validates old, enforces min 8 chars.

Admin only (`require_admin`):

- `GET /api/admin/users` → `[UserOut + {nick_count}]`.
- `POST /api/admin/users` — `{username, password, max_nicks}` → `UserOut`. `role` always `'user'`.
- `PATCH /api/admin/users/{id}` — any of `{max_nicks, is_locked, new_password}`. Cannot modify self `role`/`is_locked`.
- `DELETE /api/admin/users/{id}` — cascade. Reject if target is self or last remaining admin.

### Auth on existing routers

Replace `Depends(require_api_key)` with `Depends(get_current_user)` on:

- `nick_live` router — all queries filter `WHERE user_id = current_user.id`. `POST /api/nick-lives` checks quota before insert: `if user.max_nicks is not None and nick_count >= user.max_nicks: raise 403 "nick quota exceeded"`.
- `settings` router — upsert on `(user_id)`.
- `knowledge` router — filter by `user_id`.
- `reply_logs` router — filter by `user_id`.
- `health` router — remains public.

### Lock / delete side effects

`live_moderator` and `auto_poster` hold in-memory state keyed by nick_id. Add:

- `auto_poster.stop_user_nicks(user_id)` — stop loops for all nicks owned by user.
- `auto_poster.start_user_nicks(user_id)` — re-start.
- `moderator.drop_user(user_id)` — evict from cache.

Lock: call `stop_user_nicks`. Unlock: call `start_user_nicks`.
Delete: `stop_user_nicks` + `drop_user` then DB cascade delete.

### Security

- Passwords: bcrypt via `passlib[bcrypt]`, cost 12. Min length 8.
- Login rate limit: 5 failed attempts / 15 min / IP. In-memory counter keyed by IP (sufficient for single-instance deploy).
- Remove `APP_API_KEY` env var and `require_api_key` after all routers migrated.
- `JWT_SECRET` required; startup fails in prod if missing.

## Frontend

### Auth state

- `src/contexts/AuthContext.tsx` — `AuthProvider` wraps `<App/>`. Hook `useAuth()` returns `{token, user, login, logout}`.
- Persistence: `localStorage['auth'] = JSON.stringify({token, user})`. Rehydrate on mount.

### API client

- `src/api/client.ts` — add axios interceptor: attach `Authorization: Bearer <token>` if present; on 401/403 response → clear auth + redirect `/login`.
- SSE helper (used by LiveScan): append `?token=<token>`.

### Routes

```
/login                   public
/                        protected (Home)
/live-scan               protected
/settings                protected
/change-password         protected
/admin/users             protected + admin-only
```

`<ProtectedRoute>` — redirect `/login` if no token. `<AdminRoute>` — also check `user.role==='admin'`, else redirect `/`.

### New pages

- `pages/Login.tsx` — form username/password, error states (invalid creds, locked account, rate-limited).
- `pages/ChangePassword.tsx` — form old/new/confirm, min 8, show success toast.
- `pages/AdminUsers.tsx` — table: `username | role | max_nicks | nick_count | status | created_at | actions`. Actions: Create (modal), Edit quota, Reset password, Lock/Unlock toggle, Delete (confirm).

### Layout

- Header shows `username` + dropdown menu: **Đổi mật khẩu**, **Quản lý user** (admin only), **Đăng xuất**.
- Home: when `POST nick` returns 403 quota → toast `"Đã đạt giới hạn N nick của tài khoản"`.
- Settings page: UI unchanged; backend now scoped per-user.

## Migration (Alembic)

1. Create `users` table.
2. Seed admin from env (raise if env empty and orphan data exists).
3. Add nullable `user_id` to `nick_lives`, `settings`, `reply_logs`, `knowledge_products`.
4. Backfill all rows with `user_id = <admin_id>`.
5. Alter columns → `NOT NULL`, add FK + index.
6. `settings`: drop old singleton constraint (if any), add `UNIQUE(user_id)`.

Rollback: drop FK/columns, drop `users` table, restore old singleton constraint.

## Testing

### Backend (pytest)

Unit:

- `services/auth.py`: hash_password/verify_password, create_token/decode_token (valid, expired, tampered), quota check pure function.

Integration (FastAPI TestClient):

- Login: success returns token; wrong password → 401; locked user → 403; nonexistent → 401.
- `/auth/me` with/without token.
- Change password: wrong old → 400; too short → 422; success → subsequent login with new pwd works, old pwd fails.
- Admin CRUD: create, list (includes nick_count), update max_nicks, lock+unlock, reset password, delete cascades.
- Non-admin hitting `/admin/*` → 403.
- User A cannot see/modify user B's nicks/settings/logs (returns empty list or 404).
- Quota: user with `max_nicks=2`, POST third nick → 403.
- Delete user cascades nicks/settings/logs/knowledge.
- Delete last admin / self → 400.
- SSE accepts `?token=` query param.

Migration:

- Run against snapshot of current DB → every nick/setting/log/knowledge row backfilled with admin_id; schema matches target.

### Frontend (Playwright smoke)

- Login success → lands on `/`, header shows username.
- Wrong password → error shown, still on `/login`.
- Admin creates user → logout → login as new user works.
- Locked user cannot login.
- Change password flow end-to-end.

### Coverage target

80% on new/touched backend modules.

## Rollout

- Add `.env.example` entries: `JWT_SECRET`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`. Update README setup section.
- Drop `APP_API_KEY` from examples once migration merged.
- No data loss: migration preserves every existing row by backfilling to admin.

## Open Items

None — all design decisions resolved during brainstorm.
