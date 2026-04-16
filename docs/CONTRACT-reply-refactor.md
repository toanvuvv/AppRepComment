# CONTRACT — Reply System Refactor

**Single source of truth** for parallel implementation. All sub-agents MUST follow this spec exactly.

---

## 1. Data Model

### `NickLiveSetting` — final schema

```python
# backend/app/models/settings.py
class NickLiveSetting(Base):
    __tablename__ = "nick_live_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nick_live_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)

    # --- Reply config ---
    # reply_mode: "none" | "knowledge" | "ai" | "template"
    reply_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    reply_to_host: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reply_to_moderator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- Auto-post config ---
    auto_post_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_post_to_host: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_post_to_moderator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- Credentials (unchanged) ---
    moderator_config: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    host_config: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    host_proxy: Mapped[str | None] = mapped_column(Text, nullable=True)
```

**Removed columns:** `ai_reply_enabled`, `auto_reply_enabled`, `knowledge_reply_enabled`, `host_reply_enabled`, `host_auto_post_enabled`.

### Migration (SQLite, runs on startup in `database.py::_migrate_add_columns`)

For each nick_live_settings row, add these ALTER TABLEs:

```sql
ALTER TABLE nick_live_settings ADD COLUMN reply_mode VARCHAR(20) NOT NULL DEFAULT 'none';
ALTER TABLE nick_live_settings ADD COLUMN reply_to_host BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE nick_live_settings ADD COLUMN reply_to_moderator BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE nick_live_settings ADD COLUMN auto_post_to_host BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE nick_live_settings ADD COLUMN auto_post_to_moderator BOOLEAN NOT NULL DEFAULT 0;
```

**Data migration (run inside `_migrate_add_columns` after ALTERs, use a single SQL UPDATE):**

```sql
-- Map old → new (only if old columns still exist; wrap in try/except)
UPDATE nick_live_settings SET reply_mode = 'knowledge' WHERE knowledge_reply_enabled = 1;
UPDATE nick_live_settings SET reply_mode = 'ai' WHERE ai_reply_enabled = 1 AND knowledge_reply_enabled = 0;
UPDATE nick_live_settings SET reply_to_moderator = 1 WHERE auto_reply_enabled = 1;
UPDATE nick_live_settings SET reply_to_host = 1 WHERE host_reply_enabled = 1;
UPDATE nick_live_settings SET auto_post_to_moderator = 1 WHERE auto_post_enabled = 1;
UPDATE nick_live_settings SET auto_post_to_host = 1 WHERE host_auto_post_enabled = 1;
```

Old columns can stay in DB (SQLite doesn't drop easily) — just stop using them in code.

---

## 2. Pydantic Schemas

```python
# backend/app/schemas/settings.py
from typing import Literal

ReplyMode = Literal["none", "knowledge", "ai", "template"]

class NickLiveSettingsUpdate(BaseModel):
    reply_mode: ReplyMode | None = None
    reply_to_host: bool | None = None
    reply_to_moderator: bool | None = None
    auto_post_enabled: bool | None = None
    auto_post_to_host: bool | None = None
    auto_post_to_moderator: bool | None = None
    host_proxy: str | None = None

class NickLiveSettingsResponse(BaseModel):
    nick_live_id: int
    reply_mode: ReplyMode
    reply_to_host: bool
    reply_to_moderator: bool
    auto_post_enabled: bool
    auto_post_to_host: bool
    auto_post_to_moderator: bool
    model_config = {"from_attributes": True}
```

**Delete all old field names** from these schemas.

---

## 3. Cache Snapshot (`nick_cache.py::NickSettingsSnapshot`)

```python
@dataclass(frozen=True)
class NickSettingsSnapshot:
    reply_mode: str                     # "none" | "knowledge" | "ai" | "template"
    reply_to_host: bool
    reply_to_moderator: bool
    auto_post_enabled: bool
    auto_post_to_host: bool
    auto_post_to_moderator: bool
    host_config: dict | None
    moderator_config: dict | None       # NEW — for moderator channel check
    openai_api_key: str | None
    openai_model: str | None
    system_prompt: str
    knowledge_model: str | None
    knowledge_system_prompt: str
    banned_words: tuple[str, ...]
```

Remove all old `*_enabled` fields from the snapshot.

---

## 4. Message Builders in `live_moderator.py`

**Four explicit builders. Each returns `dict[str, Any] | None`.**

### `generate_moderator_post_body(nick_live_id, content)` — type 102, plain

```python
inner = {"type": 102, "content": content}
return {
    "content": json.dumps(inner, ensure_ascii=False),
    "send_ts": int(time.time() * 1000),
    "usersig": config["usersig"],
    "uuid": config["uuid"],
}
```
(config = `self._configs.get(nick_live_id)` — moderator config)

### `generate_moderator_reply_body(nick_live_id, guest_name, guest_id, reply_text)` — type 102 with mention
Existing `generate_reply_body` — rename to `generate_moderator_reply_body`. Keep placeholder/content_v2 structure unchanged. (type 102)

### `generate_host_post_body(nick_live_id, content)` — type 101, plain
Existing, simplify signature (remove `use_host` arg — host-only now). Uses `self._host_configs`.

### `generate_host_reply_body(nick_live_id, guest_name, guest_id, reply_text)` — type 101 with @mention
Already fixed in previous session. Keep as-is. Plain content = `f"@{guest_name} {reply_text}"`, `{"type": 101, "content": ...}`, `pin: false`.

### Senders

- `send_moderator_message(nick_live_id, session_id, body)` — existing `send_reply_raw` logic
- `send_host_message(nick_live_id, session_id, body, cookies)` — existing, keep

Rename for clarity: `send_reply_raw` → `send_moderator_message`.

---

## 5. `reply_dispatcher.py` — Routing Logic

Replace the entire `_handle` decision tree:

```python
async def _handle(self, ...):
    settings = await nick_cache.get_settings(nick_live_id, SessionLocal)

    # --- Skip if nothing to do ---
    if settings.reply_mode == "none":
        return
    if not settings.reply_to_host and not settings.reply_to_moderator:
        return

    # --- Generate reply text ---
    reply_text = None
    product_order = None
    if settings.reply_mode == "knowledge":
        # existing knowledge flow; require products
        ...
    elif settings.reply_mode == "ai":
        # existing AI flow
        ...
    elif settings.reply_mode == "template":
        # NEW: pick random reply template for this nick
        templates = svc.get_reply_templates_for_nick(nick_live_id)
        if not templates:
            log & return
        reply_text = random.choice(templates).content

    if not reply_text:
        return

    # Apply banned-words filter (existing)
    ...

    # --- Send to enabled channels ---
    if settings.reply_to_moderator and moderator.has_config(nick_live_id):
        body = moderator.generate_moderator_reply_body(
            nick_live_id, username, int(user_id), reply_text
        )
        result = await moderator.send_moderator_message(nick_live_id, session_id, body)
        # log with reply_type=f"mod_{mode}"

    if settings.reply_to_host and moderator.has_host_config(nick_live_id):
        body = moderator.generate_host_reply_body(
            nick_live_id, username, int(user_id), reply_text
        )
        result = await moderator.send_host_message(nick_live_id, session_id, body, cookies)
        # log with reply_type=f"host_{mode}"
```

**Log `reply_type` format:** `"mod_knowledge"`, `"mod_ai"`, `"mod_template"`, `"host_knowledge"`, `"host_ai"`, `"host_template"`.

---

## 6. `auto_poster.py` — Independent Channel Routing

Replace `_send`:

```python
async def _send(self, nick_live_id, session_id, cookies, content) -> dict:
    settings = await nick_cache.get_settings(nick_live_id, SessionLocal)
    results = []

    if settings.auto_post_to_host and self._moderator.has_host_config(nick_live_id):
        body = self._moderator.generate_host_post_body(nick_live_id, content)
        if body:
            r = await self._moderator.send_host_message(nick_live_id, session_id, body, cookies)
            results.append(("host", r))

    if settings.auto_post_to_moderator and self._moderator.has_config(nick_live_id):
        body = self._moderator.generate_moderator_post_body(nick_live_id, content)
        if body:
            r = await self._moderator.send_moderator_message(nick_live_id, session_id, body)
            results.append(("moderator", r))

    if not results:
        return {"success": False, "error": "no_channel_enabled"}

    # Log one reply_log entry per channel with distinct reply_type
    # (auto_poster should iterate results and log individually)
    ...
    return {"success": any(r[1].get("success") for r in results)}
```

**Log `reply_type` for auto-post:** `"autopost_host"`, `"autopost_moderator"`.

Start condition (`start()`): require `auto_post_enabled=true` AND at least one of `auto_post_to_host`/`auto_post_to_moderator` true AND config present.

---

## 7. `settings_service.py::update_nick_settings` — New Signature + Validation

```python
def update_nick_settings(
    self,
    nick_live_id: int,
    *,
    reply_mode: str | None = None,
    reply_to_host: bool | None = None,
    reply_to_moderator: bool | None = None,
    auto_post_enabled: bool | None = None,
    auto_post_to_host: bool | None = None,
    auto_post_to_moderator: bool | None = None,
    host_proxy: str | None = None,
) -> NickLiveSetting:
    row = self.get_or_create_nick_settings(nick_live_id)

    # --- Validate reply_mode ---
    if reply_mode is not None:
        if reply_mode not in ("none", "knowledge", "ai", "template"):
            raise ValueError(f"invalid reply_mode: {reply_mode}")
        if reply_mode == "knowledge":
            n = self._db.query(KnowledgeProduct).filter_by(nick_live_id=nick_live_id).count()
            if n == 0:
                raise ValueError("Cần import sản phẩm trước khi bật Knowledge AI")
        elif reply_mode == "template":
            n = self._db.query(ReplyTemplate).filter_by(nick_live_id=nick_live_id).count()
            if n == 0:
                raise ValueError("Cần tạo template reply trước khi bật chế độ Template")
        elif reply_mode == "ai":
            if not self.get_openai_api_key():
                raise ValueError("Cần cấu hình OpenAI API key trước")
        row.reply_mode = reply_mode

    # --- Validate channel toggles ---
    if reply_to_host is True and not row.host_config:
        raise ValueError("Cần Get Credentials cho host trước khi bật Reply Host")
    if reply_to_moderator is True and not row.moderator_config:
        raise ValueError("Cần cấu hình cURL moderator trước khi bật Reply Moderator")
    if auto_post_to_host is True and not row.host_config:
        raise ValueError("Cần Get Credentials cho host trước khi bật Auto Post Host")
    if auto_post_to_moderator is True and not row.moderator_config:
        raise ValueError("Cần cấu hình cURL moderator trước khi bật Auto Post Moderator")

    # --- Validate auto_post_enabled ---
    if auto_post_enabled is True:
        n = self._db.query(AutoPostTemplate).filter_by(nick_live_id=nick_live_id).count()
        if n == 0:
            raise ValueError("Cần tạo template auto-post trước khi bật")

    # Apply updates
    if reply_to_host is not None: row.reply_to_host = reply_to_host
    if reply_to_moderator is not None: row.reply_to_moderator = reply_to_moderator
    if auto_post_enabled is not None: row.auto_post_enabled = auto_post_enabled
    if auto_post_to_host is not None: row.auto_post_to_host = auto_post_to_host
    if auto_post_to_moderator is not None: row.auto_post_to_moderator = auto_post_to_moderator
    if host_proxy is not None: row.host_proxy = host_proxy

    self._db.commit()
    self._db.refresh(row)
    return row
```

---

## 8. Router `nick_live.py::update_nick_settings`

```python
@router.put("/{nick_live_id}/settings", response_model=NickLiveSettingsResponse)
def update_nick_settings(
    nick_live_id: int, payload: NickLiveSettingsUpdate, db: Session = Depends(get_db)
):
    svc = SettingsService(db)
    try:
        row = svc.update_nick_settings(
            nick_live_id,
            reply_mode=payload.reply_mode,
            reply_to_host=payload.reply_to_host,
            reply_to_moderator=payload.reply_to_moderator,
            auto_post_enabled=payload.auto_post_enabled,
            auto_post_to_host=payload.auto_post_to_host,
            auto_post_to_moderator=payload.auto_post_to_moderator,
            host_proxy=payload.host_proxy,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    from app.services.nick_cache import nick_cache
    nick_cache.invalidate_settings(nick_live_id)
    return row
```

---

## 9. Frontend — TypeScript Types

```typescript
// frontend/src/api/settings.ts
export type ReplyMode = "none" | "knowledge" | "ai" | "template";

export interface NickLiveSettings {
  nick_live_id: number;
  reply_mode: ReplyMode;
  reply_to_host: boolean;
  reply_to_moderator: boolean;
  auto_post_enabled: boolean;
  auto_post_to_host: boolean;
  auto_post_to_moderator: boolean;
}

export interface NickLiveSettingsUpdate {
  reply_mode?: ReplyMode;
  reply_to_host?: boolean;
  reply_to_moderator?: boolean;
  auto_post_enabled?: boolean;
  auto_post_to_host?: boolean;
  auto_post_to_moderator?: boolean;
  host_proxy?: string;
}
```

**Delete old `ai_reply_enabled`, `auto_reply_enabled`, `host_reply_enabled`, `knowledge_reply_enabled`, `host_auto_post_enabled` from all files.**

---

## 10. Frontend UI — `NickConfigModal.tsx` Reply Config Tab

```
┌─ Cấu hình Reply ────────────────────────────┐
│ Chế độ reply:  [ Dropdown: None / Knowledge AI / AI thường / Template ]
│                                              │
│ Kênh gửi reply:                             │
│  [ ] Host channel      (disable nếu chưa có host_config)
│  [ ] Moderator channel (disable nếu chưa có moderator_config)
└──────────────────────────────────────────────┘

┌─ Cấu hình Auto Post ────────────────────────┐
│  [ ] Bật Auto Post                          │
│                                              │
│  Kênh gửi auto post:                        │
│   [ ] Host channel                          │
│   [ ] Moderator channel                     │
└──────────────────────────────────────────────┘
```

On toggle: call PUT settings. If 422 → `message.error(detail)`. If 200 → `message.success`.

---

## 11. Frontend UI — `LiveScan.tsx` "Cài đặt tự động" Card

Replace existing 4 switches + status tags with:
- Dropdown for `reply_mode`
- Two switches for `reply_to_host` / `reply_to_moderator`
- Switch for `auto_post_enabled`
- Two switches for `auto_post_to_host` / `auto_post_to_moderator`
- Status tag: `"Reply: {mode} → {channels}"` (e.g. `"Reply: Knowledge AI → Host + Moderator"`)
- **Delete** the "Đang reply bằng template ngẫu nhiên" dead-code tag

---

## 12. Log `reply_type` enum — Final Values

| Source | Value |
|---|---|
| Reply via moderator (knowledge mode) | `mod_knowledge` |
| Reply via moderator (ai mode) | `mod_ai` |
| Reply via moderator (template mode) | `mod_template` |
| Reply via host (knowledge mode) | `host_knowledge` |
| Reply via host (ai mode) | `host_ai` |
| Reply via host (template mode) | `host_template` |
| Auto-post via moderator | `autopost_moderator` |
| Auto-post via host | `autopost_host` |

---

## 13. Files Each Agent Touches (No Overlap)

### Agent 1 — Data Layer
- `backend/app/models/settings.py`
- `backend/app/schemas/settings.py`
- `backend/app/database.py`

### Agent 2 — Services
- `backend/app/services/live_moderator.py`
- `backend/app/services/reply_dispatcher.py`
- `backend/app/services/auto_poster.py`
- `backend/app/services/settings_service.py`
- `backend/app/services/nick_cache.py`

### Agent 3 — Router
- `backend/app/routers/nick_live.py`

### Agent 4 — Frontend
- `frontend/src/api/settings.ts`
- `frontend/src/api/hostConfig.ts`
- `frontend/src/components/NickConfigModal.tsx`
- `frontend/src/pages/LiveScan.tsx`
- `frontend/src/pages/Settings.tsx` (only if it references deleted fields)

---

## 14. Non-Goals / Out of Scope

- Not dropping old DB columns (leave in schema, stop referencing)
- Not changing reply_log schema
- Not changing knowledge product / auto-post template / reply template CRUD endpoints
- Not changing scanner / comments / sessions logic

---

## 15. Smoke Test Checklist (Phase 2)

1. Backend starts, migration runs, no errors
2. GET `/api/nick-lives/1/settings` returns new schema (reply_mode, etc.)
3. PUT `reply_mode=knowledge` without products → 422 with Vietnamese message
4. PUT `reply_to_host=true` without host_config → 422
5. Enable `reply_mode=ai` + `reply_to_moderator=true` → viewer comment → moderator reply sent (type 102)
6. Enable `reply_to_host=true` additionally → viewer comment → both channels fire
7. Auto-post with `auto_post_to_host=true` → type 101 body sent
8. Auto-post with `auto_post_to_moderator=true` → type 102 body sent (plain, no placeholders)
9. Frontend shows new UI with no references to old fields, no console errors
