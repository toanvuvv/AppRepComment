# Host Comment Feature — Design Spec

**Date:** 2026-04-16
**Status:** Draft
**Author:** Claude + toanvuvv

---

## 1. Overview

Add "Host Comment" capability alongside the existing Moderator Comment flow. The live stream host can:

1. **Auto-post** (type 101): Scheduled broadcast messages rotated from per-nick templates
2. **Host reply** (type 102): Reply/mention commenters using host credentials
3. **Manual comment** (type 101): One-off message from UI

Host and Moderator operate **independently** (Approach A) — both can be enabled simultaneously, run in parallel, and do not coordinate with each other.

---

## 2. Architecture Approach

**Extend `ShopeeLiveModerator`** (Approach A) rather than creating a separate class:

- Host and Moderator both POST to the same endpoint (`/api/v1/session/{id}/message`)
- Share retry logic, rate limiter, error handling
- Differ only in: credentials source, headers, and trigger mechanism
- Auto-post worker lives in a new file `auto_poster.py` to keep `live_moderator.py` focused

---

## 3. Data Model Changes

### 3.1 `nick_live_settings` — new columns

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `host_config` | TEXT (EncryptedString, nullable) | NULL | JSON: `{usersig, uuid}` |
| `host_proxy` | TEXT (nullable) | NULL | Proxy per nick for relive.vn |
| `host_reply_enabled` | BOOLEAN | false | Host auto-reply toggle |
| `host_auto_post_enabled` | BOOLEAN | false | Host auto-post toggle |

### 3.2 `app_settings` — new row

| Key | Value | Description |
|-----|-------|-------------|
| `relive_api_key` | string | API key for relive.vn (global) |

### 3.3 `auto_post_templates` — add column

| Column | Type | Description |
|--------|------|-------------|
| `nick_live_id` | INTEGER (FK → nick_live.id, nullable) | Per-nick ownership |

- Existing rows with `nick_live_id = NULL` are legacy/global (migration)
- New templates always created with a `nick_live_id`

### 3.4 `reply_templates` — add column

| Column | Type | Description |
|--------|------|-------------|
| `nick_live_id` | INTEGER (FK → nick_live.id, nullable) | Per-nick ownership |

Same migration strategy as auto_post_templates.

### 3.5 Host Config JSON structure

Stored in `nick_live_settings.host_config` (encrypted at rest):

```json
{
  "usersig": "d27o0LjK...",
  "uuid": "TT7CEtyINToI..."
}
```

Cookies are NOT stored here — read from `nick_live.cookies` at send time.
Headers are NOT stored — hardcoded in code.

---

## 4. Relive.vn Integration

### 4.1 New service: `backend/app/services/relive_service.py`

```python
async def get_host_credentials(cookies: str, proxy: str | None, api_key: str) -> dict:
    """
    POST https://api.relive.vn/livestream/preview
    Body: { apikey, cookie, country: "vn", proxy }

    Returns: { usersig, uuid }
    Parses:
      - uuid = response.data.uuid
      - usersig = response.data.preview_config.usersig
    """
```

### 4.2 API endpoint

```
POST /api/nick-lives/{nick_live_id}/host/get-credentials
```

- No request body — reads cookies + proxy + relive_api_key from DB
- On success: saves to `nick_live_settings.host_config`, returns `{ status: "saved", uuid: "..." }`
- On failure: returns `{ error: "..." }`
- "Get lại" button calls the same endpoint, overwrites existing host_config

### 4.3 Credentials lifecycle

- **No TTL** — get once, store in DB, use indefinitely
- **Manual refresh** via "Get lại" button in UI
- Stored encrypted in `nick_live_settings.host_config`

---

## 5. Host Message Sending

### 5.1 Hardcoded headers

```python
_HOST_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "vi-VN,vi;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6,en;q=0.5",
    "content-type": "application/json",
    "origin": "https://live.shopee.vn",
    "priority": "u=1, i",
    "sec-ch-ua": '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
    "x-sz-sdk-version": "1.12.27",
}
```

`referer` is set dynamically: `https://live.shopee.vn/pc/live?session={session_id}`
`cookie` is read from `nick_live.cookies` at send time.

### 5.2 New methods on `ShopeeLiveModerator`

**`generate_host_post_body(nick_live_id, content)`** — type 101:
```json
{
  "content": "{\"type\":101,\"content\":\"message text\"}",
  "send_ts": 1713...,
  "usersig": "<from host_config>",
  "uuid": "<from host_config>",
  "pin": false
}
```

**`generate_host_reply_body(nick_live_id, guest_name, guest_id, reply_text)`** — type 102:
Same placeholder/mention logic as moderator's `generate_reply_body()`, but uses host_config's usersig/uuid.

**`generate_moderator_post_body(nick_live_id, content)`** — type 101 for moderator:
Same as host post body but uses moderator_config's usersig/uuid and moderator headers.

**`send_host_message(nick_live_id, session_id, body)`** — send with host credentials:
- Headers: `_HOST_HEADERS` + dynamic referer + cookie from nick_live
- Retry logic identical to `send_reply()`
- Uses shared `shopee_limiter`

### 5.3 Capability matrix

| | Type 101 (self comment) | Type 102 (reply mention) |
|---|---|---|
| **Moderator** | `generate_moderator_post_body()` → `send_reply()` | `generate_reply_body()` → `send_reply()` (existing) |
| **Host** | `generate_host_post_body()` → `send_host_message()` | `generate_host_reply_body()` → `send_host_message()` |

---

## 6. Auto-Post Worker

### 6.1 New file: `backend/app/services/auto_poster.py`

```python
class AutoPoster:
    _tasks: dict[int, asyncio.Task]       # nick_live_id → running task
    _template_index: dict[int, int]       # nick_live_id → current index
```

### 6.2 Flow

```
UI clicks "Start Auto-post" for nick X
    ↓
POST /api/nick-lives/{nick_live_id}/auto-post/start
    body: { session_id }
    ↓
AutoPoster.start(nick_live_id, session_id)
    ↓
_auto_post_loop(nick_live_id, session_id):
  1. Load per-nick auto_post_templates from DB
  2. Pick next template (rotate sequentially via _template_index)
  3. Sleep random(min_interval, max_interval)
  4. Determine credentials:
     - host_config exists → send_host_message() type 101
     - only moderator_config → send_reply() type 101
     - neither → log error, stop
  5. Log result to reply_logs
  6. Repeat from step 2
    ↓
UI clicks "Stop Auto-post"
    ↓
POST /api/nick-lives/{nick_live_id}/auto-post/stop
    → cancels async task
```

### 6.3 API endpoints

```
POST /api/nick-lives/{nick_live_id}/auto-post/start   body: { session_id }
POST /api/nick-lives/{nick_live_id}/auto-post/stop
GET  /api/nick-lives/{nick_live_id}/auto-post/status   → { running: bool }
```

### 6.4 Credential priority for auto-post

1. If `host_config` exists → use Host (type 101, hardcoded headers)
2. If only `moderator_config` → use Moderator (type 101, cURL headers)
3. If neither → cannot start, return error

---

## 7. Host Reply Integration

### 7.1 Reply Dispatcher changes

In `reply_dispatcher._handle()`, after the existing moderator reply logic:

```
Comment arrives
    ↓
Check auto_reply_enabled + moderator_config → moderator replies (existing)
Check host_reply_enabled + host_config → host replies (new)
Both enabled → both reply independently
Neither → skip
```

### 7.2 Reply mode selection

Both Host and Moderator share the same reply mode toggles:

- `ai_reply_enabled` → LLM generates reply (shared OpenAI config)
- `knowledge_reply_enabled` → Knowledge-based reply (shared config)
- Neither → use per-nick reply templates (template rotation)

### 7.3 Per-nick settings (complete list)

| Toggle | Description |
|--------|-------------|
| `auto_reply_enabled` | Moderator auto-reply (existing) |
| `ai_reply_enabled` | Use AI for replies (existing, shared) |
| `knowledge_reply_enabled` | Use Knowledge for replies (existing, shared) |
| `host_reply_enabled` | **New** — Host auto-reply type 102 |
| `host_auto_post_enabled` | **New** — Host auto-post type 101 |

---

## 8. Config Scope Summary

| Config | Scope | Location |
|--------|-------|----------|
| OpenAI API key, model, system prompt | **Global** | Settings page |
| Knowledge AI config | **Global** | Settings page |
| Banned words | **Global** | Settings page |
| Relive API key | **Global** | Settings page |
| Auto-post templates | **Per-nick** | Nick popup |
| Reply templates | **Per-nick** | Nick popup |
| Host proxy | **Per-nick** | Nick popup |
| Host credentials (usersig/uuid) | **Per-nick** | Nick popup |
| All toggles | **Per-nick** | Nick popup |
| Moderator cURL config | **Per-nick** | Nick popup (moved from LiveScan) |

---

## 9. Frontend: Nick Config Popup

Triggered by clicking a nick on LiveScan page. Modal/Drawer with tabs:

### Tab 1: Host Config
- Input: proxy (text, optional, placeholder: `http:host:port:user:pass`)
- Button: "Get Credentials" → calls `POST /api/nick-lives/{id}/host/get-credentials`
- Status display: "Chua co" / "Da lay (uuid: TT7C...)"
- Button: "Get lai" (same endpoint, overwrites)

### Tab 2: Auto-post
- Toggle: `host_auto_post_enabled`
- CRUD list: auto-post templates (content + min/max interval seconds)
- Buttons: Start / Stop auto-post
- Status badge: running / stopped

### Tab 3: Reply Config
- Toggle: `auto_reply_enabled` (moderator reply)
- Toggle: `host_reply_enabled` (host reply)
- Toggle: `ai_reply_enabled`
- Toggle: `knowledge_reply_enabled`
- CRUD list: reply templates (for template mode)

### Tab 4: Moderator
- TextArea: paste cURL (existing save-curl flow, moved here)
- Status: moderator config saved / not saved

---

## 10. New Files

| File | Purpose |
|------|---------|
| `backend/app/services/relive_service.py` | Relive.vn API integration |
| `backend/app/services/auto_poster.py` | Auto-post worker loop |
| `backend/migrations/add_host_config.py` | DB migration |
| `frontend/src/components/NickConfigPopup.tsx` | Nick config modal |
| `frontend/src/api/hostConfig.ts` | Host config API calls |
| `frontend/src/api/autoPost.ts` | Auto-post API calls |

---

## 11. Modified Files

| File | Changes |
|------|---------|
| `backend/app/models/settings.py` | Add columns to NickLiveSetting, add nick_live_id to templates |
| `backend/app/services/live_moderator.py` | Add host methods, hardcoded headers, moderator type 101 |
| `backend/app/services/reply_dispatcher.py` | Add host reply path |
| `backend/app/services/nick_cache.py` | Cache host_config + new toggles |
| `backend/app/services/settings_service.py` | Per-nick template queries |
| `backend/app/routers/nick_live.py` | New endpoints (host credentials, auto-post start/stop) |
| `backend/app/routers/settings.py` | Add relive_api_key, keep global settings |
| `backend/app/schemas/nick_live.py` | New request/response schemas |
| `backend/app/schemas/settings.py` | Update template schemas with nick_live_id |
| `frontend/src/pages/LiveScan.tsx` | Add nick click → open popup |
| `frontend/src/pages/Settings.tsx` | Remove per-nick templates, add relive API key |
| `frontend/src/api/settings.ts` | Add relive_api_key API |
