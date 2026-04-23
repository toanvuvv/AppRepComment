# System Keys & Per-User AI Key Mode

**Date:** 2026-04-23
**Status:** Draft — pending implementation plan
**Related:** `docs/superpowers/specs/2026-04-16-host-comment-design.md`, migration 008

## Problem

Today every setting in `app_settings` is per-user (UNIQUE `(user_id, key)` after migration 008). Two issues:

1. **Relive API key** is a paid external credential that should be centrally managed. Forcing each user to paste it is wasteful and leaks the key to anyone with a user account.
2. **OpenAI API key** is the same story for users who should consume a shared key, but power users want to bring their own for isolation or billing.

Admins have no surface to set system-level credentials, and no way to tell individual users which mode (own key vs system key) they should operate in.

## Goals

- Relive API key becomes **system-only**: one value, admin-managed, all users consume it transparently.
- OpenAI API key + model becomes **per-user mode**: each user is flagged `own` or `system` by the admin.
  - `own` → user configures their own `openai_api_key` and `openai_model` in Settings, as today.
  - `system` → user consumes the admin's system key and model. User cannot override key/model but still owns their own system prompt, knowledge prompt, knowledge model, and banned words.
- No silent fallback: a user in `own` mode without a key gets a clear error, not the system key.
- Admin UI to manage system keys + assign mode per user.
- User Settings UI hides the OpenAI key card when in `system` mode, and hides Relive from non-admins entirely.

## Non-Goals

- Migrating existing per-user values into the new system slots. DB will be wiped on deploy; admin will re-set.
- Usage quotas / billing attribution per user. Out of scope for this change.
- Changing how `ai_system_prompt`, `knowledge_system_prompt`, `knowledge_model`, `banned_words` are scoped. Those remain per-user in both modes.

## Decisions (locked)

1. **Shared in `system` mode = key + model only.** Everything else stays per-user.
2. **No fallback.** `own` mode without a key fails loudly.
3. **DB wipe on deploy.** Migration still ships for a clean upgrade path, but no data preservation for the affected keys.
4. **Admin system-keys UI lives inside `Settings.tsx`** gated by role, not a new page.
5. **Non-admin user in `system` mode sees no OpenAI key card.** Just a small badge. Non-admins never see the Relive card.

## Data Model

### `users` — add column

```
ai_key_mode  VARCHAR(10)  NOT NULL  DEFAULT 'system'
```

Enum enforced at the Pydantic layer (`Literal['own','system']`). Skip a SQL `CHECK` constraint to avoid SQLite table-recreate churn during the ALTER.

### `app_settings` — no schema change

After migration 008 the table already supports `user_id IS NULL` rows. The following keys exist **only** as `user_id = NULL` rows going forward:

| Key | Meaning |
|---|---|
| `relive_api_key` | System-wide Relive credential |
| `system_openai_api_key` | System-wide OpenAI key (used only when user's `ai_key_mode='system'`) |
| `system_openai_model` | System-wide OpenAI model |

Using distinct key names (`system_openai_*`) avoids collision with the existing per-user `openai_api_key` / `openai_model` rows, which stay scoped to the owning `user_id`.

Per-user keys (unchanged): `openai_api_key`, `openai_model`, `ai_system_prompt`, `knowledge_system_prompt`, `knowledge_model`, `banned_words`.

## Resolver Logic

Add two methods to `SettingsService`; **do not modify** `get_openai_api_key` to keep upstream impact small.

```python
def resolve_openai_config(self, ai_key_mode: str) -> tuple[str | None, str | None]:
    """Return (api_key, model) per the user's mode. No fallback.

    - mode='system': read user_id=NULL rows system_openai_api_key / system_openai_model
    - mode='own':    read per-user openai_api_key / openai_model for self._user_id
    """

def get_system_relive_api_key(self) -> str | None:
    """Read user_id=NULL row for relive_api_key regardless of self._user_id."""
```

Callers pass the user's `ai_key_mode` in (they already hold the `User` model). No join gymnastics inside `SettingsService`.

### Call-site updates

| Call-site | Change |
|---|---|
| `nick_cache._load_settings_sync` | Load `User.ai_key_mode` for the nick owner, call `resolve_openai_config(mode)`, store resolved key+model on the snapshot. |
| `settings.test_ai` | Use `resolve_openai_config(current_user.ai_key_mode)`. Error messages distinguish own-unset vs system-unset. |
| `settings_service.update_nick_settings` (reply_mode='ai' validation) | Same — resolve by owner's mode; reject with specific message. |
| `auto_pinner._load_api_key` | Call `get_system_relive_api_key()`. Stop reading per-user row. |
| `knowledge.parse_products_from_relive` | Same. |
| `nick_live.host_get_credentials` | Same. |

## API Surface

### Admin-only (new)

```
GET  /api/admin/system-keys
PUT  /api/admin/system-keys/relive   body: { api_key: string }
PUT  /api/admin/system-keys/openai   body: { api_key: string, model: string }
```

`GET` returns:
```json
{
  "relive_api_key_set": true,
  "openai_api_key_set": true,
  "openai_model": "gpt-4o"
}
```

Never echoes the key values. Each PUT invalidates the whole `nick_cache._settings` dict (existing pattern).

### User management (update)

- `UserCreate`, `UserUpdate`, `UserOut` add optional/required `ai_key_mode: Literal['own','system']` (default `'system'` in create).
- `PATCH /api/admin/users/{id}` accepts `ai_key_mode`. On change, invalidate cached snapshots for every nick owned by that user.

### User-facing (update)

- `GET /api/settings/openai` response adds:
  ```
  ai_key_mode: 'own' | 'system'
  is_managed_by_admin: boolean   # true when mode === 'system'
  ```
  Frontend uses `is_managed_by_admin` to hide the key input card.
- `PUT /api/settings/openai` returns 403 if caller's `ai_key_mode === 'system'`. Users in system mode cannot overwrite their per-user key through this route.
- **Remove** `GET|PUT /api/settings/relive-api-key` for non-admins. Either delete the routes and surface admin-only routes instead (preferred), or gate them with `require_admin`. Spec picks **delete** to avoid two code paths.
- `GET /api/auth/me` (or current equivalent) returns `ai_key_mode` so the UI can branch immediately after login.

## UI Changes

### `Settings.tsx`

- Read `role` and `ai_key_mode` from auth context.
- **OpenAI card**
  - `ai_key_mode === 'own'`: render as today.
  - `ai_key_mode === 'system'`: replace with a compact banner:
    `<Tag color="blue">AI key: hệ thống</Tag>` + `"Admin đã cấu hình OpenAI. Liên hệ admin để đổi."`
- **Relive card**: render only when `role === 'admin'`.
- **New "System Keys" section** (admin only): two cards — System Relive, System OpenAI (password input + model select). Separate visually from the admin's own per-user OpenAI card when admin's `ai_key_mode === 'own'`.

### `AdminUsers.tsx`

- Table: add "AI Key Mode" column with inline `<Select options=[own, system]>`; onChange → `PATCH /api/admin/users/{id}`.
- Table: add "Own key set?" indicator column — renders `✅`/`❌` when `ai_key_mode === 'own'`, `—` otherwise. Requires admin-only endpoint to check per-user key-set flags; simplest approach is to extend `list_users` response with `openai_own_key_set: boolean`.
- Create-user modal: add `<Form.Item name="ai_key_mode">` default `'system'`.

### Frontend API clients

- `frontend/src/api/admin.ts`: add `getSystemKeys`, `updateSystemRelive`, `updateSystemOpenAI`; `UserUpdate` / `UserCreate` / `AdminUser` types gain `ai_key_mode`; `AdminUser` gains `openai_own_key_set`.
- `frontend/src/api/settings.ts`: `OpenAIConfig` response type gains `ai_key_mode`, `is_managed_by_admin`.

## Validation Rules

- `update_nick_settings` setting `reply_mode='ai'`:
  - Owner `ai_key_mode='own'` + no per-user `openai_api_key` → `400 "Cần cấu hình OpenAI API key (chế độ own)"`.
  - Owner `ai_key_mode='system'` + no `system_openai_api_key` → `400 "Admin chưa cấu hình System OpenAI key"`.
- `test_ai`: same two-case error mapping.
- `PUT /api/settings/openai` by a user with `ai_key_mode='system'` → `403 "Tài khoản đang dùng system key; không thể tự cấu hình"`.

## Migration `010_system_keys_and_ai_mode.py`

```
1. ALTER TABLE users ADD COLUMN ai_key_mode VARCHAR(10) NOT NULL DEFAULT 'system'
   (SQLite supports adding a NOT NULL column with a constant DEFAULT.)

2. DELETE FROM app_settings WHERE key = 'relive_api_key'
   (Drops any legacy per-user rows. Admin re-sets via the new system endpoint.)

3. DELETE FROM app_settings
   WHERE user_id IS NULL AND key IN ('openai_api_key','openai_model')
   (Belt-and-suspenders: avoid ambiguity with the new system_openai_* keys.)
```

No seeding. Admin will set values through the UI post-deploy.

## Test Plan

### Backend (pytest)

- `test_settings_service.py`
  - `resolve_openai_config('system')` returns the `user_id=NULL` pair and ignores per-user rows.
  - `resolve_openai_config('own')` returns the per-user pair; returns `(None, None)` when unset (no fallback).
  - `get_system_relive_api_key()` returns the system row regardless of `self._user_id`.
- `test_admin.py`
  - Non-admin request to `/api/admin/system-keys/*` → 403.
  - Admin `PUT /api/admin/system-keys/relive` writes `user_id=NULL` row and calls `_invalidate_all_nick_settings`.
  - `PATCH /api/admin/users/{id}` with `ai_key_mode` updates column and invalidates snapshots for nicks of that user.
- `test_nick_settings_ai_mode.py` (new)
  - `reply_mode='ai'` with owner `own` + no key → 400 own-unset message.
  - `reply_mode='ai'` with owner `system` + no system key → 400 system-unset message.
  - `reply_mode='ai'` succeeds in each mode when the relevant key is set.
- `test_auto_pinner.py`
  - Case where a stale per-user `relive_api_key` row exists but only system row is authoritative — pinner must read the system row.
- `test_migration_010.py` (new)
  - Post-migration: `users.ai_key_mode` exists and defaults to `'system'`.
  - Any pre-existing `relive_api_key` rows are removed.

### Frontend (manual checklist)

- Non-admin, `ai_key_mode='system'`: Settings shows no OpenAI card (badge only), no Relive card.
- Non-admin, `ai_key_mode='own'`: Settings shows OpenAI card as today, no Relive card.
- Admin: Settings shows System Keys section; can set both system keys and see confirmation.
- AdminUsers: mode select inline-update round-trips; create-user form defaults to `system`.

## File Impact

| File | Change |
|---|---|
| `backend/migrations/010_system_keys_and_ai_mode.py` | new |
| `backend/app/models/user.py` | add `ai_key_mode` |
| `backend/app/schemas/user.py` | add `ai_key_mode` on Create/Update/Out |
| `backend/app/schemas/settings.py` | extend `OpenAIConfigResponse`; new `SystemKeysResponse`, `SystemOpenAIUpdate`, `SystemReliveUpdate` |
| `backend/app/services/settings_service.py` | add `resolve_openai_config`, `get_system_relive_api_key`, `set_system_*` helpers |
| `backend/app/routers/admin.py` | `/system-keys/*` endpoints; accept `ai_key_mode` in user CRUD; extend `list_users` with `openai_own_key_set` |
| `backend/app/routers/settings.py` | `test_ai` and `update_nick_settings` use resolver; `update_openai_config` 403 when system mode; remove relive endpoints |
| `backend/app/routers/nick_live.py` | `host_get_credentials` reads system relive |
| `backend/app/routers/knowledge.py` | `parse_products_from_relive` reads system relive |
| `backend/app/services/auto_pinner.py` | `_load_api_key` reads system relive |
| `backend/app/services/nick_cache.py` | `_load_settings_sync` loads owner's `ai_key_mode`, resolves via helper |
| `backend/app/routers/auth.py` | `/me` returns `ai_key_mode` |
| `frontend/src/api/settings.ts` | types update |
| `frontend/src/api/admin.ts` | system-keys client; user types update |
| `frontend/src/pages/Settings.tsx` | conditional rendering; System Keys section |
| `frontend/src/pages/AdminUsers.tsx` | mode column + form field; own-key indicator |
| `backend/tests/...` | new/updated tests per plan |

## Risks & Mitigations

- **Hot path**: `nick_cache._load_settings_sync` now needs `User.ai_key_mode`. `NickLive` already exposes `user_id`, so loading the `User` row adds one small query within the already-cached snapshot lifecycle. Acceptable.
- **Upstream breakage on `get_openai_api_key`**: Mitigated by adding `resolve_openai_config` alongside rather than mutating the existing helper. GitNexus impact analysis showed 3 direct callers — each is updated explicitly.
- **Cache staleness when admin flips mode**: handled by invalidating per-user nick snapshots on `PATCH /users/{id}` and the entire settings cache on system-key writes.
- **Accidental reappearance of per-user relive rows**: migration deletes on deploy, and with the relive user routes removed there is no write path left for non-admins.

## Open Questions

None at the time of writing. All design decisions are locked (see Decisions section).
