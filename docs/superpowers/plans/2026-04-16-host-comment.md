# Host Comment Feature — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable the live stream host to self-comment (type 101), reply to comments (type 102), and auto-post scheduled messages — running independently alongside the existing moderator flow.

**Architecture:** Extend `ShopeeLiveModerator` with host credential management (usersig/uuid from relive.vn API), hardcoded browser headers, and a new `AutoPoster` worker. Templates (auto-post + reply) move to per-nick scope. Frontend gets a nick config popup (Modal with tabs).

**Tech Stack:** Python/FastAPI (backend), React/Ant Design (frontend), SQLite with SQLAlchemy ORM, httpx for HTTP calls.

**Spec:** `docs/superpowers/specs/2026-04-16-host-comment-design.md`

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `backend/app/services/relive_service.py` | Call relive.vn API to get host usersig/uuid |
| `backend/app/services/auto_poster.py` | Auto-post worker loop per nick |
| `backend/migrations/003_host_comment.py` | DB migration: new columns + per-nick templates |
| `frontend/src/components/NickConfigModal.tsx` | Nick config modal (tabs: Host, Auto-post, Reply, Moderator) |
| `frontend/src/api/hostConfig.ts` | Host config + auto-post + per-nick template API calls |

### Modified Files

| File | Changes |
|------|---------|
| `backend/app/models/settings.py` | Add columns to NickLiveSetting, nick_live_id to templates |
| `backend/app/database.py` | Migration call for 003 |
| `backend/app/services/live_moderator.py` | Host headers, host send methods, moderator type 101 |
| `backend/app/services/reply_dispatcher.py` | Host reply path in `_handle()` |
| `backend/app/services/nick_cache.py` | Cache host_config + new toggles |
| `backend/app/services/settings_service.py` | Per-nick template queries, host config, relive key |
| `backend/app/routers/nick_live.py` | Host endpoints, auto-post start/stop, per-nick templates |
| `backend/app/routers/settings.py` | Relive API key endpoint |
| `backend/app/schemas/nick_live.py` | New request/response schemas |
| `backend/app/schemas/settings.py` | Update template schemas |
| `frontend/src/pages/LiveScan.tsx` | Nick click → open modal |
| `frontend/src/pages/Settings.tsx` | Remove per-nick templates, add relive key input |
| `frontend/src/api/settings.ts` | Add relive key API, update template interfaces |

---

## Phase 1: Database & Models

### Task 1: Migration — Add host columns and per-nick FK

**Files:**
- Create: `backend/migrations/003_host_comment.py`
- Modify: `backend/app/models/settings.py`
- Modify: `backend/app/database.py`

- [ ] **Step 1: Update models — NickLiveSetting**

Add new columns to `backend/app/models/settings.py`:

```python
# In class NickLiveSetting, after knowledge_reply_enabled:
    host_config: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    host_proxy: Mapped[str | None] = mapped_column(Text, nullable=True)
    host_reply_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    host_auto_post_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

- [ ] **Step 2: Update models — Add nick_live_id to templates**

Add FK column to both template classes in `backend/app/models/settings.py`:

```python
# In class ReplyTemplate, after content:
    nick_live_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

# In class AutoPostTemplate, after content:
    nick_live_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 3: Write migration script**

Create `backend/migrations/003_host_comment.py`:

```python
"""Add host_config, host_proxy, host_reply_enabled, host_auto_post_enabled
to nick_live_settings, and nick_live_id to reply_templates / auto_post_templates."""

import logging
import sqlite3

from app.database import Base, engine

logger = logging.getLogger(__name__)


def _col_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def migrate() -> None:
    # Ensure all ORM-defined tables exist first.
    Base.metadata.create_all(bind=engine)

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        # --- nick_live_settings ---
        additions = [
            ("nick_live_settings", "host_config", "TEXT"),
            ("nick_live_settings", "host_proxy", "TEXT"),
            ("nick_live_settings", "host_reply_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
            ("nick_live_settings", "host_auto_post_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
        ]
        for table, col, col_type in additions:
            if not _col_exists(cur, table, col):
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                logger.info(f"Added {table}.{col}")

        # --- reply_templates ---
        if not _col_exists(cur, "reply_templates", "nick_live_id"):
            cur.execute("ALTER TABLE reply_templates ADD COLUMN nick_live_id INTEGER")
            logger.info("Added reply_templates.nick_live_id")

        # --- auto_post_templates ---
        if not _col_exists(cur, "auto_post_templates", "nick_live_id"):
            cur.execute("ALTER TABLE auto_post_templates ADD COLUMN nick_live_id INTEGER")
            logger.info("Added auto_post_templates.nick_live_id")

        raw.commit()
        logger.info("Migration 003_host_comment complete")
    finally:
        raw.close()
```

- [ ] **Step 4: Wire migration into init_db**

In `backend/app/database.py`, add the import and call after existing migrations:

```python
from app.migrations import _003_host_comment as m003

# Inside init_db(), after existing migration calls:
m003.migrate()
```

Note: Check the existing import pattern in `database.py` — it may use `from migrations.xxx` or `from app.migrations.xxx`. Follow whichever pattern is already there. Also rename the file to match the import convention used (e.g., `_003_host_comment.py` if that's how 001/002 are imported).

- [ ] **Step 5: Verify migration runs**

Run:
```bash
cd backend && python -c "from app.database import init_db; init_db()"
```
Expected: logs showing "Added nick_live_settings.host_config", etc. No errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/settings.py backend/migrations/003_host_comment.py backend/app/database.py
git commit -m "feat: add host_config columns and per-nick template FK (migration 003)"
```

---

## Phase 2: Backend Services

### Task 2: Relive.vn Service

**Files:**
- Create: `backend/app/services/relive_service.py`

- [ ] **Step 1: Create relive_service.py**

```python
"""Fetch host credentials (usersig + uuid) from relive.vn API."""

import logging
from typing import Any

from app.services.http_client import get_client

logger = logging.getLogger(__name__)

_RELIVE_URL = "https://api.relive.vn/livestream/preview"


async def get_host_credentials(
    cookies: str,
    api_key: str,
    proxy: str | None = None,
) -> dict[str, Any]:
    """Call relive.vn to obtain usersig and uuid for the host.

    Returns {"usersig": str, "uuid": str} on success.
    Raises ValueError on failure with a descriptive message.
    """
    payload: dict[str, Any] = {
        "apikey": api_key,
        "cookie": cookies,
        "country": "vn",
    }
    if proxy:
        payload["proxy"] = proxy

    client = get_client()
    try:
        resp = await client.post(_RELIVE_URL, json=payload, timeout=30.0)
    except Exception as exc:
        raise ValueError(f"Relive.vn request failed: {exc}") from exc

    if resp.status_code != 200:
        raise ValueError(
            f"Relive.vn returned status {resp.status_code}: {resp.text[:300]}"
        )

    try:
        data = resp.json()
    except Exception as exc:
        raise ValueError(f"Relive.vn returned invalid JSON: {exc}") from exc

    # Navigate response: data.uuid, data.preview_config.usersig
    root = data.get("data") or data
    uuid_val = root.get("uuid")
    usersig = None
    preview_config = root.get("preview_config")
    if isinstance(preview_config, dict):
        usersig = preview_config.get("usersig")

    if not uuid_val or not usersig:
        raise ValueError(
            f"Relive.vn response missing uuid or usersig. "
            f"Keys in data: {list(root.keys()) if isinstance(root, dict) else 'N/A'}"
        )

    return {"usersig": usersig, "uuid": uuid_val}
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/relive_service.py
git commit -m "feat: add relive.vn service for host credentials"
```

---

### Task 3: Settings Service — Per-nick templates + host config

**Files:**
- Modify: `backend/app/services/settings_service.py`

- [ ] **Step 1: Add per-nick template query methods**

Add these methods to `SettingsService` class in `backend/app/services/settings_service.py`:

```python
    # --- Per-nick reply templates ---

    def get_reply_templates_for_nick(self, nick_live_id: int) -> list[ReplyTemplate]:
        return (
            self._db.query(ReplyTemplate)
            .filter(ReplyTemplate.nick_live_id == nick_live_id)
            .order_by(ReplyTemplate.created_at)
            .all()
        )

    def create_reply_template_for_nick(
        self, nick_live_id: int, content: str
    ) -> ReplyTemplate:
        tmpl = ReplyTemplate(content=content, nick_live_id=nick_live_id)
        self._db.add(tmpl)
        self._db.commit()
        self._db.refresh(tmpl)
        return tmpl

    def delete_reply_template_for_nick(
        self, nick_live_id: int, template_id: int
    ) -> bool:
        tmpl = (
            self._db.query(ReplyTemplate)
            .filter(ReplyTemplate.id == template_id, ReplyTemplate.nick_live_id == nick_live_id)
            .first()
        )
        if not tmpl:
            return False
        self._db.delete(tmpl)
        self._db.commit()
        return True

    # --- Per-nick auto-post templates ---

    def get_auto_post_templates_for_nick(
        self, nick_live_id: int
    ) -> list[AutoPostTemplate]:
        return (
            self._db.query(AutoPostTemplate)
            .filter(AutoPostTemplate.nick_live_id == nick_live_id)
            .order_by(AutoPostTemplate.created_at)
            .all()
        )

    def create_auto_post_template_for_nick(
        self,
        nick_live_id: int,
        content: str,
        min_interval: int = 60,
        max_interval: int = 300,
    ) -> AutoPostTemplate:
        tmpl = AutoPostTemplate(
            content=content,
            min_interval_seconds=min_interval,
            max_interval_seconds=max_interval,
            nick_live_id=nick_live_id,
        )
        self._db.add(tmpl)
        self._db.commit()
        self._db.refresh(tmpl)
        return tmpl

    def delete_auto_post_template_for_nick(
        self, nick_live_id: int, template_id: int
    ) -> bool:
        tmpl = (
            self._db.query(AutoPostTemplate)
            .filter(
                AutoPostTemplate.id == template_id,
                AutoPostTemplate.nick_live_id == nick_live_id,
            )
            .first()
        )
        if not tmpl:
            return False
        self._db.delete(tmpl)
        self._db.commit()
        return True
```

- [ ] **Step 2: Add host config methods to update_nick_settings**

Extend the `update_nick_settings` method signature and body:

```python
    def update_nick_settings(
        self,
        nick_live_id: int,
        ai_reply_enabled: bool | None = None,
        auto_reply_enabled: bool | None = None,
        auto_post_enabled: bool | None = None,
        knowledge_reply_enabled: bool | None = None,
        host_reply_enabled: bool | None = None,
        host_auto_post_enabled: bool | None = None,
        host_proxy: str | None = ...,  # sentinel: ... means "not provided"
    ) -> NickLiveSetting:
```

Add at the end of the method body (before `db.commit()`):

```python
        if host_reply_enabled is not None:
            row.host_reply_enabled = host_reply_enabled
        if host_auto_post_enabled is not None:
            row.host_auto_post_enabled = host_auto_post_enabled
        if host_proxy is not ...:
            row.host_proxy = host_proxy
```

- [ ] **Step 3: Add host_config save/load helpers**

Add to `SettingsService`:

```python
    def save_host_config(
        self, nick_live_id: int, usersig: str, uuid: str
    ) -> NickLiveSetting:
        import json
        row = self.get_or_create_nick_settings(nick_live_id)
        row.host_config = json.dumps({"usersig": usersig, "uuid": uuid})
        self._db.commit()
        self._db.refresh(row)
        return row

    def get_host_config(self, nick_live_id: int) -> dict | None:
        import json
        row = self.get_or_create_nick_settings(nick_live_id)
        if not row.host_config:
            return None
        try:
            return json.loads(row.host_config)
        except (json.JSONDecodeError, TypeError):
            return None
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/settings_service.py
git commit -m "feat: per-nick template queries and host config helpers"
```

---

### Task 4: Nick Cache — Add host fields

**Files:**
- Modify: `backend/app/services/nick_cache.py`

- [ ] **Step 1: Extend NickSettingsSnapshot**

Add fields to the `NickSettingsSnapshot` dataclass:

```python
@dataclass(frozen=True)
class NickSettingsSnapshot:
    ai_reply_enabled: bool
    knowledge_reply_enabled: bool
    auto_reply_enabled: bool
    auto_post_enabled: bool
    host_reply_enabled: bool          # NEW
    host_auto_post_enabled: bool      # NEW
    host_config: dict | None          # NEW — {"usersig": ..., "uuid": ...}
    openai_api_key: str | None
    openai_model: str | None
    system_prompt: str
    knowledge_model: str | None
    knowledge_system_prompt: str
    banned_words: tuple[str, ...]
```

- [ ] **Step 2: Update _load_settings_sync**

In the static loader that builds the snapshot, add the new fields. Find where `NickSettingsSnapshot(...)` is constructed and add:

```python
    host_reply_enabled=bool(row.host_reply_enabled),
    host_auto_post_enabled=bool(row.host_auto_post_enabled),
    host_config=json.loads(row.host_config) if row.host_config else None,
```

Add `import json` at the top of the file if not already present.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/nick_cache.py
git commit -m "feat: cache host_config and host toggles in NickSettingsSnapshot"
```

---

### Task 5: Live Moderator — Host send methods

**Files:**
- Modify: `backend/app/services/live_moderator.py`

- [ ] **Step 1: Add hardcoded host headers constant**

After the existing `_SAFE_LOG_HEADERS` constant, add:

```python
_HOST_HEADERS: dict[str, str] = {
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
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    ),
    "x-sz-sdk-version": "1.12.27",
}
```

- [ ] **Step 2: Add generate_host_post_body (type 101)**

Add method to `ShopeeLiveModerator`:

```python
    def generate_host_post_body(
        self, nick_live_id: int, content: str, *, use_host: bool = True
    ) -> dict[str, Any] | None:
        """Build type-101 (self-comment) body.

        use_host=True  -> uses host_config credentials
        use_host=False -> uses moderator_config credentials (moderator type 101)
        """
        if use_host:
            config = self._host_configs.get(nick_live_id)
        else:
            config = self._configs.get(nick_live_id)
        if not config:
            return None

        inner_content = {"type": 101, "content": content}
        return {
            "content": json.dumps(inner_content, ensure_ascii=False),
            "send_ts": int(time.time() * 1000),
            "usersig": config["usersig"],
            "uuid": config["uuid"],
            "pin": False,
        }
```

- [ ] **Step 3: Add generate_host_reply_body (type 102)**

```python
    def generate_host_reply_body(
        self,
        nick_live_id: int,
        guest_name: str,
        guest_id: int,
        reply_text: str,
    ) -> dict[str, Any] | None:
        """Build type-102 mention body using host credentials."""
        config = self._host_configs.get(nick_live_id)
        if not config:
            return None

        placeholder = re.sub(
            r"[^A-Z0-9]",
            "",
            guest_name.upper()[:8] + str(int(time.time())),
        )[-10:]

        inner_content = {
            "content": f"@{guest_name} {reply_text}",
            "content_v2": f"#{placeholder}# {reply_text}",
            "extra_info": {
                "feedback_transparent": "",
                "place_holders": [
                    {
                        "key": f"#{placeholder}#",
                        "type": 1,
                        "user_id": guest_id,
                        "value": guest_name,
                    }
                ],
            },
            "type": 102,
        }

        return {
            "content": json.dumps(inner_content, ensure_ascii=False),
            "send_ts": int(time.time() * 1000),
            "usersig": config["usersig"],
            "uuid": config["uuid"],
        }
```

- [ ] **Step 4: Add send_host_message**

```python
    async def send_host_message(
        self,
        nick_live_id: int,
        live_session_id: int,
        body: dict[str, Any],
        cookies: str,
    ) -> dict[str, Any]:
        """Send message using host credentials with hardcoded headers.

        Same retry/error logic as send_reply().
        """
        headers = {**_HOST_HEADERS}
        headers["referer"] = (
            f"https://live.shopee.vn/pc/live?session={live_session_id}"
        )
        headers["cookie"] = cookies

        url = f"https://{_REQUIRED_HOST}/api/v1/session/{live_session_id}/message"
        logger.debug(f"[host] URL: {url}")

        attempts = 0
        max_attempts = 2
        while attempts < max_attempts:
            attempts += 1
            try:
                await shopee_limiter.acquire()
                client = get_client()
                resp = await client.post(
                    url, headers=headers, json=body, timeout=REPLY_TIMEOUT_SEC
                )

                status = resp.status_code

                if status in (401, 403):
                    logger.warning(
                        f"Host message auth rejected: status={status}"
                    )
                    return {
                        "success": False,
                        "status_code": status,
                        "error": "auth_expired",
                    }

                if status == 429 and attempts < max_attempts:
                    logger.warning("Host message rate limited; sleeping 2s")
                    await asyncio.sleep(2.0)
                    continue

                is_success = False
                if status == 200:
                    try:
                        resp_data = resp.json()
                        is_success = resp_data.get("err_code") == 0
                    except json.JSONDecodeError:
                        is_success = False

                if not is_success:
                    logger.warning(
                        f"Host message failed: status={status} | "
                        f"body={resp.text[:500]}"
                    )
                return {"success": is_success, "status_code": status}
            except Exception as e:
                logger.error(f"Host message error: {e}")
                return {"success": False, "error": "request_failed"}

        return {"success": False, "error": "rate_limited"}
```

- [ ] **Step 5: Add host config memory cache**

In `__init__`, add:

```python
    def __init__(self) -> None:
        self._configs: dict[int, dict[str, Any]] = {}
        self._host_configs: dict[int, dict[str, Any]] = {}  # NEW
```

Add methods to manage host config cache:

```python
    def save_host_config(self, nick_live_id: int, usersig: str, uuid: str) -> None:
        """Save host credentials to memory cache and database."""
        config = {"usersig": usersig, "uuid": uuid}
        self._host_configs[nick_live_id] = config
        self._persist_host_to_db(nick_live_id, config)

    def get_host_config(self, nick_live_id: int) -> dict[str, Any] | None:
        return self._host_configs.get(nick_live_id)

    def has_host_config(self, nick_live_id: int) -> bool:
        return nick_live_id in self._host_configs

    def _persist_host_to_db(self, nick_live_id: int, config: dict[str, Any]) -> None:
        db = SessionLocal()
        try:
            row = db.query(NickLiveSetting).filter(
                NickLiveSetting.nick_live_id == nick_live_id
            ).first()
            if not row:
                row = NickLiveSetting(nick_live_id=nick_live_id)
                db.add(row)
            row.host_config = json.dumps(config, ensure_ascii=False)
            db.commit()
        finally:
            db.close()
```

- [ ] **Step 6: Load host configs on startup**

Update `load_all_from_db()` to also load host configs:

```python
    def load_all_from_db(self) -> None:
        db = SessionLocal()
        try:
            rows = db.query(NickLiveSetting).filter(
                (NickLiveSetting.moderator_config.isnot(None))
                | (NickLiveSetting.host_config.isnot(None))
            ).all()
            for row in rows:
                # Moderator config
                if row.moderator_config:
                    try:
                        config = json.loads(row.moderator_config)
                        self._configs[row.nick_live_id] = config
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(f"Invalid moderator config for nick={row.nick_live_id}")
                # Host config
                if row.host_config:
                    try:
                        config = json.loads(row.host_config)
                        self._host_configs[row.nick_live_id] = config
                        logger.info(f"Loaded host config for nick={row.nick_live_id}")
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(f"Invalid host config for nick={row.nick_live_id}")
            logger.info(
                f"Loaded {len(self._configs)} moderator + "
                f"{len(self._host_configs)} host config(s)"
            )
        finally:
            db.close()
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/live_moderator.py
git commit -m "feat: host message methods (type 101/102) with hardcoded headers"
```

---

### Task 6: Auto Poster Worker

**Files:**
- Create: `backend/app/services/auto_poster.py`

- [ ] **Step 1: Create auto_poster.py**

```python
"""Auto-post worker: rotates through per-nick templates on a schedule."""

import asyncio
import logging
import random
from typing import Any

from app.database import SessionLocal
from app.services.live_moderator import ShopeeLiveModerator
from app.services.reply_log_writer import reply_log_writer
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


class AutoPoster:
    def __init__(self, moderator: ShopeeLiveModerator) -> None:
        self._moderator = moderator
        self._tasks: dict[int, asyncio.Task] = {}
        self._template_index: dict[int, int] = {}

    def is_running(self, nick_live_id: int) -> bool:
        task = self._tasks.get(nick_live_id)
        return task is not None and not task.done()

    async def start(
        self,
        nick_live_id: int,
        session_id: int,
        cookies: str,
    ) -> dict[str, Any]:
        if self.is_running(nick_live_id):
            return {"status": "already_running"}

        # Check that at least one credential set exists
        has_host = self._moderator.has_host_config(nick_live_id)
        has_mod = self._moderator.has_config(nick_live_id)
        if not has_host and not has_mod:
            return {"error": "No host or moderator credentials configured"}

        # Check templates exist
        db = SessionLocal()
        try:
            svc = SettingsService(db)
            templates = svc.get_auto_post_templates_for_nick(nick_live_id)
        finally:
            db.close()

        if not templates:
            return {"error": "No auto-post templates for this nick"}

        self._template_index[nick_live_id] = 0
        task = asyncio.create_task(
            self._loop(nick_live_id, session_id, cookies)
        )
        self._tasks[nick_live_id] = task
        logger.info(f"Auto-post started for nick={nick_live_id}")
        return {"status": "started"}

    async def stop(self, nick_live_id: int) -> dict[str, Any]:
        task = self._tasks.pop(nick_live_id, None)
        self._template_index.pop(nick_live_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info(f"Auto-post stopped for nick={nick_live_id}")
            return {"status": "stopped"}
        return {"status": "not_running"}

    def stop_all(self) -> None:
        for nick_id in list(self._tasks):
            task = self._tasks.pop(nick_id)
            if not task.done():
                task.cancel()
        self._template_index.clear()

    async def _loop(
        self,
        nick_live_id: int,
        session_id: int,
        cookies: str,
    ) -> None:
        try:
            while True:
                # Reload templates each cycle (picks up CRUD changes)
                db = SessionLocal()
                try:
                    svc = SettingsService(db)
                    templates = svc.get_auto_post_templates_for_nick(nick_live_id)
                finally:
                    db.close()

                if not templates:
                    logger.warning(f"No templates for nick={nick_live_id}, stopping auto-post")
                    break

                # Rotate through templates
                idx = self._template_index.get(nick_live_id, 0) % len(templates)
                tmpl = templates[idx]
                self._template_index[nick_live_id] = idx + 1

                # Sleep random interval
                interval = random.uniform(
                    tmpl.min_interval_seconds, tmpl.max_interval_seconds
                )
                logger.debug(
                    f"Auto-post nick={nick_live_id}: sleeping {interval:.0f}s "
                    f"before posting template {tmpl.id}"
                )
                await asyncio.sleep(interval)

                # Send message — prefer host, fallback to moderator
                result = await self._send(nick_live_id, session_id, cookies, tmpl.content)

                # Log
                reply_log_writer.enqueue({
                    "nick_live_id": nick_live_id,
                    "session_id": session_id,
                    "guest_name": "[auto-post]",
                    "guest_id": 0,
                    "comment_text": "",
                    "reply_text": tmpl.content,
                    "outcome": "success" if result.get("success") else "failed",
                    "error": result.get("error"),
                    "status_code": result.get("status_code"),
                    "latency_ms": 0,
                    "llm_latency_ms": 0,
                    "cached_hit": False,
                })

        except asyncio.CancelledError:
            logger.info(f"Auto-post loop cancelled for nick={nick_live_id}")
        except Exception:
            logger.exception(f"Auto-post loop crashed for nick={nick_live_id}")
        finally:
            self._tasks.pop(nick_live_id, None)
            self._template_index.pop(nick_live_id, None)

    async def _send(
        self,
        nick_live_id: int,
        session_id: int,
        cookies: str,
        content: str,
    ) -> dict[str, Any]:
        # Prefer host credentials
        if self._moderator.has_host_config(nick_live_id):
            body = self._moderator.generate_host_post_body(
                nick_live_id, content, use_host=True
            )
            if body:
                return await self._moderator.send_host_message(
                    nick_live_id, session_id, body, cookies
                )

        # Fallback to moderator credentials (type 101)
        if self._moderator.has_config(nick_live_id):
            body = self._moderator.generate_host_post_body(
                nick_live_id, content, use_host=False
            )
            if body:
                return await self._moderator.send_reply_raw(
                    nick_live_id, session_id, body
                )

        return {"success": False, "error": "no_credentials"}
```

- [ ] **Step 2: Add send_reply_raw to ShopeeLiveModerator**

This sends a pre-built body using moderator headers (for moderator type 101). Add to `live_moderator.py`:

```python
    async def send_reply_raw(
        self,
        nick_live_id: int,
        live_session_id: int,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Send a pre-built body using moderator headers. Used for type 101."""
        config = self._configs.get(nick_live_id)
        if not config:
            return {"success": False, "error": "Moderator not configured"}

        url = f"https://{_REQUIRED_HOST}/api/v1/session/{live_session_id}/message"

        attempts = 0
        max_attempts = 2
        while attempts < max_attempts:
            attempts += 1
            try:
                await shopee_limiter.acquire()
                client = get_client()
                resp = await client.post(
                    url, headers=config["headers"], json=body, timeout=REPLY_TIMEOUT_SEC
                )
                status = resp.status_code

                if status in (401, 403):
                    return {"success": False, "status_code": status, "error": "auth_expired"}
                if status == 429 and attempts < max_attempts:
                    await asyncio.sleep(2.0)
                    continue

                is_success = False
                if status == 200:
                    try:
                        is_success = resp.json().get("err_code") == 0
                    except json.JSONDecodeError:
                        pass
                return {"success": is_success, "status_code": status}
            except Exception as e:
                logger.error(f"send_reply_raw error: {e}")
                return {"success": False, "error": "request_failed"}

        return {"success": False, "error": "rate_limited"}
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/auto_poster.py backend/app/services/live_moderator.py
git commit -m "feat: auto-poster worker with template rotation"
```

---

### Task 7: Reply Dispatcher — Host reply path

**Files:**
- Modify: `backend/app/services/reply_dispatcher.py`

- [ ] **Step 1: Add host reply logic to _handle**

In `_handle()`, after the existing moderator send block (around line 377-401), add a second block for host reply. The key is that both can fire independently:

```python
        # ---- Host reply (independent of moderator) ----
        if snapshot.host_reply_enabled and self._moderator.has_host_config(nick_live_id):
            host_reply_text = reply_text  # reuse LLM-generated text if available
            if not host_reply_text:
                # If moderator path was skipped (no moderator config), we still
                # need to generate a reply for the host path.
                # This block mirrors the LLM generation above.
                pass  # TODO in next iteration if needed

            if host_reply_text:
                host_body = self._moderator.generate_host_reply_body(
                    nick_live_id, guest_name, guest_id, host_reply_text
                )
                if host_body:
                    host_result = await self._moderator.send_host_message(
                        nick_live_id, session_id, host_body, cookies
                    )
                    reply_log_writer.enqueue({
                        **base_log,
                        "reply_text": host_reply_text,
                        "outcome": "success" if host_result.get("success") else "failed",
                        "error": host_result.get("error"),
                        "status_code": host_result.get("status_code"),
                        "latency_ms": 0,
                        "llm_latency_ms": 0,
                        "cached_hit": True,  # reused from moderator generation
                    })
```

Note: When both moderator and host are enabled, the LLM reply text is generated once and reused for both sends. If only host is enabled (no moderator config), the existing LLM generation code path will need to run for the host too. Refactor the LLM generation block to run when EITHER `auto_reply_enabled` or `host_reply_enabled` is true, and the send blocks to run independently based on their own toggle.

- [ ] **Step 2: Adjust the guard conditions for LLM generation**

Change the early-return check at the moderator config check (around line 203) from:

```python
if not moderator.has_config(nick_live_id):
    # log no_config and return
```

To:

```python
has_mod = moderator.has_config(nick_live_id) and snapshot.auto_reply_enabled
has_host = moderator.has_host_config(nick_live_id) and snapshot.host_reply_enabled
if not has_mod and not has_host:
    reply_log_writer.enqueue({**base_log, "reply_text": "", "outcome": "no_config", ...})
    return
```

This ensures LLM generation happens if EITHER path needs a reply.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/reply_dispatcher.py
git commit -m "feat: host reply path in dispatcher (independent of moderator)"
```

---

## Phase 3: API Endpoints

### Task 8: Schemas — New request/response types

**Files:**
- Modify: `backend/app/schemas/nick_live.py`
- Modify: `backend/app/schemas/settings.py`

- [ ] **Step 1: Add host schemas to nick_live.py**

```python
class HostGetCredentialsResponse(BaseModel):
    status: str
    uuid: str | None = None
    error: str | None = None


class HostConfigStatus(BaseModel):
    configured: bool
    uuid: str | None = None
    has_usersig: bool = False
    proxy: str | None = None


class AutoPostStartRequest(BaseModel):
    session_id: int


class AutoPostStatusResponse(BaseModel):
    running: bool


class HostPostRequest(BaseModel):
    """Manual host comment (type 101)."""
    content: str = Field(..., min_length=1, max_length=2000)
    session_id: int
```

- [ ] **Step 2: Update NickLiveSettingsUpdate and Response**

In `backend/app/schemas/settings.py`, add the new toggles:

```python
class NickLiveSettingsUpdate(BaseModel):
    ai_reply_enabled: bool | None = None
    auto_reply_enabled: bool | None = None
    auto_post_enabled: bool | None = None
    knowledge_reply_enabled: bool | None = None
    host_reply_enabled: bool | None = None           # NEW
    host_auto_post_enabled: bool | None = None       # NEW
    host_proxy: str | None = None                    # NEW


class NickLiveSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    nick_live_id: int
    ai_reply_enabled: bool
    auto_reply_enabled: bool
    auto_post_enabled: bool
    knowledge_reply_enabled: bool
    host_reply_enabled: bool                          # NEW
    host_auto_post_enabled: bool                      # NEW
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/nick_live.py backend/app/schemas/settings.py
git commit -m "feat: schemas for host config, auto-post, and updated toggles"
```

---

### Task 9: Router — Host endpoints + per-nick templates

**Files:**
- Modify: `backend/app/routers/nick_live.py`
- Modify: `backend/app/routers/settings.py`

- [ ] **Step 1: Add host credential endpoint**

In `backend/app/routers/nick_live.py`:

```python
from app.services.relive_service import get_host_credentials

@router.post("/{nick_live_id}/host/get-credentials")
async def get_host_creds(nick_live_id: int, db: Session = Depends(get_db)):
    """Fetch usersig+uuid from relive.vn and save to host_config."""
    nick = db.query(NickLive).filter(NickLive.id == nick_live_id).first()
    if not nick:
        raise HTTPException(status_code=404, detail="Nick not found")

    svc = SettingsService(db)
    relive_key = svc.get_setting("relive_api_key")
    if not relive_key:
        raise HTTPException(status_code=400, detail="Relive API key not configured")

    row = svc.get_or_create_nick_settings(nick_live_id)
    proxy = row.host_proxy

    try:
        creds = await get_host_credentials(nick.cookies, relive_key, proxy)
    except ValueError as e:
        return {"status": "error", "error": str(e)}

    svc.save_host_config(nick_live_id, creds["usersig"], creds["uuid"])
    moderator.save_host_config(nick_live_id, creds["usersig"], creds["uuid"])
    nick_cache.invalidate_settings(nick_live_id)

    return {"status": "saved", "uuid": creds["uuid"]}
```

- [ ] **Step 2: Add host config status endpoint**

```python
@router.get("/{nick_live_id}/host/status")
def get_host_status(nick_live_id: int, db: Session = Depends(get_db)):
    svc = SettingsService(db)
    config = svc.get_host_config(nick_live_id)
    row = svc.get_or_create_nick_settings(nick_live_id)
    return {
        "configured": config is not None,
        "uuid": config.get("uuid") if config else None,
        "has_usersig": bool(config and config.get("usersig")),
        "proxy": row.host_proxy,
    }
```

- [ ] **Step 3: Add auto-post start/stop/status endpoints**

```python
from app.services.auto_poster import AutoPoster

# Singleton — initialize in main.py alongside moderator
# For now, import from where it's created
# auto_poster: AutoPoster will be created in main.py

@router.post("/{nick_live_id}/auto-post/start")
async def start_auto_post(
    nick_live_id: int,
    payload: AutoPostStartRequest,
    db: Session = Depends(get_db),
):
    nick = db.query(NickLive).filter(NickLive.id == nick_live_id).first()
    if not nick:
        raise HTTPException(status_code=404, detail="Nick not found")

    from app.main import auto_poster
    result = await auto_poster.start(nick_live_id, payload.session_id, nick.cookies)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{nick_live_id}/auto-post/stop")
async def stop_auto_post(nick_live_id: int):
    from app.main import auto_poster
    return await auto_poster.stop(nick_live_id)


@router.get("/{nick_live_id}/auto-post/status")
def get_auto_post_status(nick_live_id: int):
    from app.main import auto_poster
    return {"running": auto_poster.is_running(nick_live_id)}
```

- [ ] **Step 4: Add manual host comment endpoint**

```python
@router.post("/{nick_live_id}/host/post")
async def host_post_comment(
    nick_live_id: int,
    payload: HostPostRequest,
    db: Session = Depends(get_db),
):
    """Manual host comment (type 101)."""
    nick = db.query(NickLive).filter(NickLive.id == nick_live_id).first()
    if not nick:
        raise HTTPException(status_code=404, detail="Nick not found")

    body = moderator.generate_host_post_body(nick_live_id, payload.content, use_host=True)
    if not body:
        raise HTTPException(status_code=400, detail="Host not configured")

    result = await moderator.send_host_message(
        nick_live_id, payload.session_id, body, nick.cookies
    )
    return result
```

- [ ] **Step 5: Add per-nick template CRUD endpoints**

```python
@router.get("/{nick_live_id}/auto-post-templates")
def list_nick_auto_post_templates(nick_live_id: int, db: Session = Depends(get_db)):
    svc = SettingsService(db)
    return svc.get_auto_post_templates_for_nick(nick_live_id)


@router.post("/{nick_live_id}/auto-post-templates")
def create_nick_auto_post_template(
    nick_live_id: int,
    payload: AutoPostTemplateCreate,
    db: Session = Depends(get_db),
):
    svc = SettingsService(db)
    return svc.create_auto_post_template_for_nick(
        nick_live_id, payload.content,
        payload.min_interval_seconds, payload.max_interval_seconds,
    )


@router.put("/{nick_live_id}/auto-post-templates/{template_id}")
def update_nick_auto_post_template(
    nick_live_id: int,
    template_id: int,
    payload: AutoPostTemplateUpdate,
    db: Session = Depends(get_db),
):
    svc = SettingsService(db)
    tmpl = svc.update_auto_post_template(template_id, payload.content,
        payload.min_interval_seconds, payload.max_interval_seconds)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return tmpl


@router.delete("/{nick_live_id}/auto-post-templates/{template_id}")
def delete_nick_auto_post_template(
    nick_live_id: int, template_id: int, db: Session = Depends(get_db),
):
    svc = SettingsService(db)
    if not svc.delete_auto_post_template_for_nick(nick_live_id, template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"detail": "Deleted"}


@router.get("/{nick_live_id}/reply-templates")
def list_nick_reply_templates(nick_live_id: int, db: Session = Depends(get_db)):
    svc = SettingsService(db)
    return svc.get_reply_templates_for_nick(nick_live_id)


@router.post("/{nick_live_id}/reply-templates")
def create_nick_reply_template(
    nick_live_id: int,
    payload: ReplyTemplateCreate,
    db: Session = Depends(get_db),
):
    svc = SettingsService(db)
    return svc.create_reply_template_for_nick(nick_live_id, payload.content)


@router.delete("/{nick_live_id}/reply-templates/{template_id}")
def delete_nick_reply_template(
    nick_live_id: int, template_id: int, db: Session = Depends(get_db),
):
    svc = SettingsService(db)
    if not svc.delete_reply_template_for_nick(nick_live_id, template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"detail": "Deleted"}
```

- [ ] **Step 6: Add relive API key endpoint to settings router**

In `backend/app/routers/settings.py`:

```python
@router.get("/relive-api-key")
def get_relive_key(db: Session = Depends(get_db)):
    svc = SettingsService(db)
    key = svc.get_setting("relive_api_key")
    return {"api_key_set": bool(key), "api_key": key or ""}


@router.put("/relive-api-key")
def update_relive_key(
    payload: dict, db: Session = Depends(get_db)
):
    svc = SettingsService(db)
    svc.set_setting("relive_api_key", payload.get("api_key", ""))
    return {"status": "saved"}
```

- [ ] **Step 7: Update update_nick_settings endpoint**

In `backend/app/routers/nick_live.py`, update the `update_nick_settings` handler to pass new fields:

```python
    row = svc.update_nick_settings(
        nick_live_id,
        ai_reply_enabled=payload.ai_reply_enabled,
        auto_reply_enabled=payload.auto_reply_enabled,
        auto_post_enabled=payload.auto_post_enabled,
        knowledge_reply_enabled=payload.knowledge_reply_enabled,
        host_reply_enabled=payload.host_reply_enabled,
        host_auto_post_enabled=payload.host_auto_post_enabled,
        host_proxy=payload.host_proxy if payload.host_proxy is not None else ...,
    )
```

- [ ] **Step 8: Initialize AutoPoster in main.py**

In `backend/app/main.py`, add:

```python
from app.services.auto_poster import AutoPoster

auto_poster = AutoPoster(moderator)

@app.on_event("shutdown")
async def shutdown_auto_poster():
    auto_poster.stop_all()
```

- [ ] **Step 9: Commit**

```bash
git add backend/app/routers/nick_live.py backend/app/routers/settings.py backend/app/main.py
git commit -m "feat: host config, auto-post, per-nick template API endpoints"
```

---

## Phase 4: Frontend

### Task 10: API Layer — Host config + per-nick templates

**Files:**
- Create: `frontend/src/api/hostConfig.ts`

- [ ] **Step 1: Create hostConfig.ts**

```typescript
import axios from "axios";

const API = import.meta.env.VITE_API_URL || "";

// --- Host credentials ---

export interface HostConfigStatus {
  configured: boolean;
  uuid: string | null;
  has_usersig: boolean;
  proxy: string | null;
}

export async function getHostStatus(nickLiveId: number): Promise<HostConfigStatus> {
  const { data } = await axios.get(`${API}/api/nick-lives/${nickLiveId}/host/status`);
  return data;
}

export async function getHostCredentials(
  nickLiveId: number
): Promise<{ status: string; uuid?: string; error?: string }> {
  const { data } = await axios.post(
    `${API}/api/nick-lives/${nickLiveId}/host/get-credentials`
  );
  return data;
}

export async function hostPostComment(
  nickLiveId: number,
  content: string,
  sessionId: number
): Promise<{ success: boolean; error?: string }> {
  const { data } = await axios.post(`${API}/api/nick-lives/${nickLiveId}/host/post`, {
    content,
    session_id: sessionId,
  });
  return data;
}

// --- Auto-post ---

export interface AutoPostTemplate {
  id: number;
  content: string;
  min_interval_seconds: number;
  max_interval_seconds: number;
  nick_live_id: number;
}

export async function getAutoPostTemplates(
  nickLiveId: number
): Promise<AutoPostTemplate[]> {
  const { data } = await axios.get(
    `${API}/api/nick-lives/${nickLiveId}/auto-post-templates`
  );
  return data;
}

export async function createAutoPostTemplate(
  nickLiveId: number,
  content: string,
  minInterval: number,
  maxInterval: number
): Promise<AutoPostTemplate> {
  const { data } = await axios.post(
    `${API}/api/nick-lives/${nickLiveId}/auto-post-templates`,
    {
      content,
      min_interval_seconds: minInterval,
      max_interval_seconds: maxInterval,
    }
  );
  return data;
}

export async function updateAutoPostTemplate(
  nickLiveId: number,
  templateId: number,
  updates: Partial<{
    content: string;
    min_interval_seconds: number;
    max_interval_seconds: number;
  }>
): Promise<AutoPostTemplate> {
  const { data } = await axios.put(
    `${API}/api/nick-lives/${nickLiveId}/auto-post-templates/${templateId}`,
    updates
  );
  return data;
}

export async function deleteAutoPostTemplate(
  nickLiveId: number,
  templateId: number
): Promise<void> {
  await axios.delete(
    `${API}/api/nick-lives/${nickLiveId}/auto-post-templates/${templateId}`
  );
}

// --- Auto-post control ---

export async function startAutoPost(
  nickLiveId: number,
  sessionId: number
): Promise<{ status: string }> {
  const { data } = await axios.post(
    `${API}/api/nick-lives/${nickLiveId}/auto-post/start`,
    { session_id: sessionId }
  );
  return data;
}

export async function stopAutoPost(
  nickLiveId: number
): Promise<{ status: string }> {
  const { data } = await axios.post(
    `${API}/api/nick-lives/${nickLiveId}/auto-post/stop`
  );
  return data;
}

export async function getAutoPostStatus(
  nickLiveId: number
): Promise<{ running: boolean }> {
  const { data } = await axios.get(
    `${API}/api/nick-lives/${nickLiveId}/auto-post/status`
  );
  return data;
}

// --- Per-nick reply templates ---

export interface ReplyTemplate {
  id: number;
  content: string;
  nick_live_id: number;
}

export async function getReplyTemplates(
  nickLiveId: number
): Promise<ReplyTemplate[]> {
  const { data } = await axios.get(
    `${API}/api/nick-lives/${nickLiveId}/reply-templates`
  );
  return data;
}

export async function createReplyTemplate(
  nickLiveId: number,
  content: string
): Promise<ReplyTemplate> {
  const { data } = await axios.post(
    `${API}/api/nick-lives/${nickLiveId}/reply-templates`,
    { content }
  );
  return data;
}

export async function deleteReplyTemplate(
  nickLiveId: number,
  templateId: number
): Promise<void> {
  await axios.delete(
    `${API}/api/nick-lives/${nickLiveId}/reply-templates/${templateId}`
  );
}

// --- Nick settings ---

export interface NickLiveSettings {
  nick_live_id: number;
  ai_reply_enabled: boolean;
  auto_reply_enabled: boolean;
  auto_post_enabled: boolean;
  knowledge_reply_enabled: boolean;
  host_reply_enabled: boolean;
  host_auto_post_enabled: boolean;
}

export async function getNickSettings(
  nickLiveId: number
): Promise<NickLiveSettings> {
  const { data } = await axios.get(
    `${API}/api/nick-lives/${nickLiveId}/settings`
  );
  return data;
}

export async function updateNickSettings(
  nickLiveId: number,
  updates: Partial<NickLiveSettings & { host_proxy: string }>
): Promise<NickLiveSettings> {
  const { data } = await axios.put(
    `${API}/api/nick-lives/${nickLiveId}/settings`,
    updates
  );
  return data;
}
```

- [ ] **Step 2: Add relive key API to settings.ts**

In `frontend/src/api/settings.ts`, add:

```typescript
export async function getReliveApiKey(): Promise<{ api_key_set: boolean; api_key: string }> {
  const { data } = await axios.get(`${API}/api/settings/relive-api-key`);
  return data;
}

export async function updateReliveApiKey(api_key: string): Promise<void> {
  await axios.put(`${API}/api/settings/relive-api-key`, { api_key });
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/hostConfig.ts frontend/src/api/settings.ts
git commit -m "feat: frontend API layer for host config, auto-post, per-nick templates"
```

---

### Task 11: Nick Config Modal

**Files:**
- Create: `frontend/src/components/NickConfigModal.tsx`

- [ ] **Step 1: Create NickConfigModal.tsx**

This is the main UI component — a Modal with 4 tabs. Due to size, implement each tab as a section within the component. The modal receives `nickLiveId`, `open`, `onClose` props.

```typescript
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Button, Input, InputNumber, List, Modal, Space, Switch, Tabs,
  Typography, message, Badge, Tag, Divider,
} from "antd";
import {
  DeleteOutlined, PlusOutlined, PlayCircleOutlined,
  PauseCircleOutlined, ReloadOutlined, ThunderboltOutlined,
} from "@ant-design/icons";
import {
  type AutoPostTemplate, type HostConfigStatus, type NickLiveSettings,
  type ReplyTemplate,
  getHostStatus, getHostCredentials,
  getAutoPostTemplates, createAutoPostTemplate, updateAutoPostTemplate,
  deleteAutoPostTemplate,
  startAutoPost, stopAutoPost, getAutoPostStatus,
  getReplyTemplates, createReplyTemplate, deleteReplyTemplate,
  getNickSettings, updateNickSettings,
} from "../api/hostConfig";
import {
  type ModeratorStatus,
  getModeratorStatus, saveModeratorCurl, removeModerator,
} from "../api/nickLive"; // adjust import path to match existing

const { Text, Title } = Typography;
const { TextArea } = Input;

interface Props {
  nickLiveId: number;
  nickName: string;
  sessionId: number | null; // current live session, null if not scanning
  open: boolean;
  onClose: () => void;
}

export default function NickConfigModal({
  nickLiveId, nickName, sessionId, open, onClose,
}: Props) {
  // --- Host config state ---
  const [hostStatus, setHostStatus] = useState<HostConfigStatus | null>(null);
  const [proxy, setProxy] = useState("");
  const [credLoading, setCredLoading] = useState(false);

  // --- Auto-post state ---
  const [autoTemplates, setAutoTemplates] = useState<AutoPostTemplate[]>([]);
  const [newPostContent, setNewPostContent] = useState("");
  const [newPostMin, setNewPostMin] = useState(60);
  const [newPostMax, setNewPostMax] = useState(300);
  const [autoPostRunning, setAutoPostRunning] = useState(false);
  const [postLoading, setPostLoading] = useState(false);

  // --- Reply templates state ---
  const [replyTemplates, setReplyTemplates] = useState<ReplyTemplate[]>([]);
  const [newReplyContent, setNewReplyContent] = useState("");
  const [replyLoading, setReplyLoading] = useState(false);

  // --- Settings state ---
  const [settings, setSettings] = useState<NickLiveSettings | null>(null);

  // --- Moderator state ---
  const [modStatus, setModStatus] = useState<ModeratorStatus | null>(null);
  const [curlText, setCurlText] = useState("");
  const [curlLoading, setCurlLoading] = useState(false);

  // Debounce ref for interval updates
  const intervalTimerRef = useRef<ReturnType<typeof setTimeout>>();

  // --- Load all data on open ---
  useEffect(() => {
    if (!open) return;
    Promise.all([
      getHostStatus(nickLiveId).then(setHostStatus),
      getAutoPostTemplates(nickLiveId).then(setAutoTemplates),
      getAutoPostStatus(nickLiveId).then((s) => setAutoPostRunning(s.running)),
      getReplyTemplates(nickLiveId).then(setReplyTemplates),
      getNickSettings(nickLiveId).then(setSettings),
      getModeratorStatus(nickLiveId).then(setModStatus),
    ]).catch(() => message.error("Failed to load config"));
  }, [open, nickLiveId]);

  // Set proxy from host status
  useEffect(() => {
    if (hostStatus?.proxy) setProxy(hostStatus.proxy);
  }, [hostStatus]);

  // --- Host handlers ---
  const handleGetCredentials = async () => {
    setCredLoading(true);
    try {
      // Save proxy first
      await updateNickSettings(nickLiveId, { host_proxy: proxy || "" });
      const result = await getHostCredentials(nickLiveId);
      if (result.error) {
        message.error(result.error);
      } else {
        message.success(`Credentials saved! UUID: ${result.uuid}`);
        setHostStatus(await getHostStatus(nickLiveId));
      }
    } catch {
      message.error("Failed to get credentials");
    } finally {
      setCredLoading(false);
    }
  };

  // --- Toggle handler ---
  const handleToggle = async (field: string, value: boolean) => {
    try {
      const updated = await updateNickSettings(nickLiveId, { [field]: value });
      setSettings(updated);
    } catch {
      message.error("Failed to update setting");
    }
  };

  // --- Auto-post handlers ---
  const handleAddAutoPost = async () => {
    if (!newPostContent.trim()) return;
    setPostLoading(true);
    try {
      await createAutoPostTemplate(nickLiveId, newPostContent, newPostMin, newPostMax);
      setAutoTemplates(await getAutoPostTemplates(nickLiveId));
      setNewPostContent("");
    } catch {
      message.error("Failed to create template");
    } finally {
      setPostLoading(false);
    }
  };

  const handleDeleteAutoPost = async (id: number) => {
    try {
      await deleteAutoPostTemplate(nickLiveId, id);
      setAutoTemplates((prev) => prev.filter((t) => t.id !== id));
    } catch {
      message.error("Failed to delete");
    }
  };

  const handleUpdateInterval = useCallback(
    (id: number, min: number, max: number) => {
      clearTimeout(intervalTimerRef.current);
      setAutoTemplates((prev) =>
        prev.map((t) =>
          t.id === id ? { ...t, min_interval_seconds: min, max_interval_seconds: max } : t
        )
      );
      intervalTimerRef.current = setTimeout(async () => {
        await updateAutoPostTemplate(nickLiveId, id, {
          min_interval_seconds: min,
          max_interval_seconds: max,
        });
      }, 800);
    },
    [nickLiveId]
  );

  const handleStartAutoPost = async () => {
    if (!sessionId) {
      message.warning("Start scan first");
      return;
    }
    try {
      await startAutoPost(nickLiveId, sessionId);
      setAutoPostRunning(true);
      message.success("Auto-post started");
    } catch (e: any) {
      message.error(e.response?.data?.detail || "Failed to start");
    }
  };

  const handleStopAutoPost = async () => {
    try {
      await stopAutoPost(nickLiveId);
      setAutoPostRunning(false);
      message.success("Auto-post stopped");
    } catch {
      message.error("Failed to stop");
    }
  };

  // --- Reply template handlers ---
  const handleAddReply = async () => {
    if (!newReplyContent.trim()) return;
    setReplyLoading(true);
    try {
      await createReplyTemplate(nickLiveId, newReplyContent);
      setReplyTemplates(await getReplyTemplates(nickLiveId));
      setNewReplyContent("");
    } catch {
      message.error("Failed to create template");
    } finally {
      setReplyLoading(false);
    }
  };

  const handleDeleteReply = async (id: number) => {
    try {
      await deleteReplyTemplate(nickLiveId, id);
      setReplyTemplates((prev) => prev.filter((t) => t.id !== id));
    } catch {
      message.error("Failed to delete");
    }
  };

  // --- Moderator handlers ---
  const handleSaveCurl = async () => {
    if (!curlText.trim()) return;
    setCurlLoading(true);
    try {
      const result = await saveModeratorCurl(nickLiveId, curlText);
      if (result.error) {
        message.error(result.error);
      } else {
        message.success("Moderator cURL saved");
        setModStatus(await getModeratorStatus(nickLiveId));
        setCurlText("");
      }
    } catch {
      message.error("Failed to save cURL");
    } finally {
      setCurlLoading(false);
    }
  };

  const tabItems = [
    {
      key: "host",
      label: "Host Config",
      children: (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <Text strong>Proxy (optional)</Text>
            <Input
              placeholder="http:host:port:user:pass"
              value={proxy}
              onChange={(e) => setProxy(e.target.value)}
              style={{ marginTop: 4 }}
            />
          </div>
          <div>
            <Text strong>Host Credentials</Text>
            <div style={{ marginTop: 8 }}>
              {hostStatus?.configured ? (
                <Tag color="green">UUID: {hostStatus.uuid?.slice(0, 12)}...</Tag>
              ) : (
                <Tag color="default">Chua co</Tag>
              )}
            </div>
            <Space style={{ marginTop: 8 }}>
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                loading={credLoading}
                onClick={handleGetCredentials}
              >
                {hostStatus?.configured ? "Get lai" : "Get Credentials"}
              </Button>
            </Space>
          </div>
        </Space>
      ),
    },
    {
      key: "autopost",
      label: (
        <span>
          Auto-post{" "}
          {autoPostRunning && <Badge status="processing" />}
        </span>
      ),
      children: (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Space>
            <Text strong>Auto-post:</Text>
            <Switch
              checked={settings?.host_auto_post_enabled}
              onChange={(v) => handleToggle("host_auto_post_enabled", v)}
            />
            {autoPostRunning ? (
              <Button danger icon={<PauseCircleOutlined />} onClick={handleStopAutoPost}>
                Stop
              </Button>
            ) : (
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                onClick={handleStartAutoPost}
                disabled={!settings?.host_auto_post_enabled}
              >
                Start
              </Button>
            )}
          </Space>
          <Divider style={{ margin: "8px 0" }} />
          <TextArea
            rows={2}
            placeholder="Noi dung comment (VD: Mua ngay giam 50%!)"
            value={newPostContent}
            onChange={(e) => setNewPostContent(e.target.value)}
          />
          <Space>
            <Text>Interval:</Text>
            <InputNumber min={10} max={86400} value={newPostMin}
              onChange={(v) => setNewPostMin(v || 60)} addonAfter="s min" />
            <InputNumber min={10} max={86400} value={newPostMax}
              onChange={(v) => setNewPostMax(v || 300)} addonAfter="s max" />
            <Button type="primary" icon={<PlusOutlined />}
              onClick={handleAddAutoPost} loading={postLoading}>Them</Button>
          </Space>
          <List
            dataSource={autoTemplates}
            locale={{ emptyText: "Chua co template nao" }}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button key="del" type="text" danger size="small"
                    icon={<DeleteOutlined />}
                    onClick={() => handleDeleteAutoPost(item.id)} />,
                ]}
              >
                <Space direction="vertical" size="small" style={{ flex: 1 }}>
                  <Text>{item.content}</Text>
                  <Space size="small">
                    <InputNumber min={10} size="small" value={item.min_interval_seconds}
                      onChange={(v) => handleUpdateInterval(item.id, v || 10, item.max_interval_seconds)}
                      addonAfter="s" />
                    <Text type="secondary">~</Text>
                    <InputNumber min={10} size="small" value={item.max_interval_seconds}
                      onChange={(v) => handleUpdateInterval(item.id, item.min_interval_seconds, v || 10)}
                      addonAfter="s" />
                  </Space>
                </Space>
              </List.Item>
            )}
          />
        </Space>
      ),
    },
    {
      key: "reply",
      label: "Reply Config",
      children: (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Space direction="vertical" size="small">
            <Space>
              <Text>Moderator auto-reply:</Text>
              <Switch checked={settings?.auto_reply_enabled}
                onChange={(v) => handleToggle("auto_reply_enabled", v)} />
            </Space>
            <Space>
              <Text>Host auto-reply:</Text>
              <Switch checked={settings?.host_reply_enabled}
                onChange={(v) => handleToggle("host_reply_enabled", v)} />
            </Space>
            <Space>
              <Text>AI reply:</Text>
              <Switch checked={settings?.ai_reply_enabled}
                onChange={(v) => handleToggle("ai_reply_enabled", v)} />
            </Space>
            <Space>
              <Text>Knowledge reply:</Text>
              <Switch checked={settings?.knowledge_reply_enabled}
                onChange={(v) => handleToggle("knowledge_reply_enabled", v)} />
            </Space>
          </Space>
          <Divider style={{ margin: "8px 0" }} />
          <Text strong>Reply Templates (non-AI mode)</Text>
          <Space>
            <Input placeholder="Template content..."
              value={newReplyContent}
              onChange={(e) => setNewReplyContent(e.target.value)}
              onPressEnter={handleAddReply} />
            <Button type="primary" icon={<PlusOutlined />}
              onClick={handleAddReply} loading={replyLoading}>Them</Button>
          </Space>
          <List
            dataSource={replyTemplates}
            locale={{ emptyText: "Chua co template nao" }}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button key="del" type="text" danger size="small"
                    icon={<DeleteOutlined />}
                    onClick={() => handleDeleteReply(item.id)} />,
                ]}
              >
                <Text>{item.content}</Text>
              </List.Item>
            )}
          />
        </Space>
      ),
    },
    {
      key: "moderator",
      label: "Moderator",
      children: (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <Text strong>Status: </Text>
            {modStatus?.configured ? (
              <Tag color="green">Configured (host: {modStatus.host_id})</Tag>
            ) : (
              <Tag color="default">Not configured</Tag>
            )}
          </div>
          <TextArea
            rows={4}
            placeholder="Paste cURL command here..."
            value={curlText}
            onChange={(e) => setCurlText(e.target.value)}
          />
          <Button type="primary" onClick={handleSaveCurl} loading={curlLoading}>
            Save cURL
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Modal
      title={`Config: ${nickName}`}
      open={open}
      onCancel={onClose}
      footer={null}
      width={700}
      destroyOnClose
    >
      <Tabs items={tabItems} />
    </Modal>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/NickConfigModal.tsx
git commit -m "feat: NickConfigModal with 4 tabs (host, auto-post, reply, moderator)"
```

---

### Task 12: LiveScan — Open modal on nick click

**Files:**
- Modify: `frontend/src/pages/LiveScan.tsx`

- [ ] **Step 1: Add modal state and import**

Add import:
```typescript
import NickConfigModal from "../components/NickConfigModal";
```

Add state:
```typescript
const [configNick, setConfigNick] = useState<{ id: number; name: string } | null>(null);
```

- [ ] **Step 2: Add click handler to nick table**

In the nick table columns, add an onClick or a "Config" button. Find the columns definition for the nick table and add an action column:

```typescript
{
  title: "",
  key: "config",
  width: 60,
  render: (_: unknown, record: NickLive) => (
    <Button
      size="small"
      icon={<SettingOutlined />}
      onClick={() => setConfigNick({ id: record.id, name: record.name })}
    />
  ),
}
```

Add `SettingOutlined` to the antd icon imports.

- [ ] **Step 3: Render the modal**

At the bottom of the component JSX (before closing fragment/div):

```tsx
<NickConfigModal
  nickLiveId={configNick?.id ?? 0}
  nickName={configNick?.name ?? ""}
  sessionId={/* current scanning session ID for this nick */}
  open={!!configNick}
  onClose={() => setConfigNick(null)}
/>
```

Note: you'll need to pass the correct `sessionId` for the selected nick. Check how `scanStatus` is tracked per nick in LiveScan — it's likely stored in a map. Pass `scanStatuses[configNick.id]?.session_id ?? null`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/LiveScan.tsx
git commit -m "feat: config button on nick table opens NickConfigModal"
```

---

### Task 13: Settings Page — Add relive key, clean up per-nick sections

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`

- [ ] **Step 1: Add relive API key section**

Add state:
```typescript
const [reliveKey, setReliveKey] = useState("");
const [reliveKeySet, setReliveKeySet] = useState(false);
const [reliveLoading, setReliveLoading] = useState(false);
```

Add load in useEffect:
```typescript
getReliveApiKey().then((r) => {
  setReliveKeySet(r.api_key_set);
  if (r.api_key) setReliveKey(r.api_key);
});
```

Add save handler:
```typescript
const handleSaveReliveKey = async () => {
  setReliveLoading(true);
  try {
    await updateReliveApiKey(reliveKey);
    setReliveKeySet(!!reliveKey);
    message.success("Relive API key saved");
  } catch {
    message.error("Failed to save");
  } finally {
    setReliveLoading(false);
  }
};
```

Add UI card (after OpenAI config card):
```tsx
<Card title="Relive.vn API Key" style={{ marginBottom: 16 }}>
  <Space>
    <Input.Password
      placeholder="Relive API key"
      value={reliveKey}
      onChange={(e) => setReliveKey(e.target.value)}
      style={{ width: 400 }}
    />
    <Button type="primary" onClick={handleSaveReliveKey} loading={reliveLoading}>
      Save
    </Button>
    {reliveKeySet && <Tag color="green">Set</Tag>}
  </Space>
</Card>
```

Add imports:
```typescript
import { getReliveApiKey, updateReliveApiKey } from "../api/settings";
```

- [ ] **Step 2: Remove auto-post and reply template sections from Settings**

These are now per-nick in the NickConfigModal. Remove:
- The auto-post templates Card and all related state/handlers
- The reply templates Card and all related state/handlers
- The corresponding imports from `../api/settings`

Keep: OpenAI config, system prompt, knowledge AI, banned words, relive key.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Settings.tsx
git commit -m "feat: add relive key config, remove per-nick sections from Settings"
```

---

## Phase 5: Integration & Verification

### Task 14: End-to-end verification

- [ ] **Step 1: Start backend and verify migration**

```bash
cd backend && python -m uvicorn app.main:app --reload
```

Check logs for: "Migration 003_host_comment complete", "Loaded X moderator + Y host config(s)".

- [ ] **Step 2: Verify new API endpoints respond**

```bash
# Relive key
curl -X GET http://localhost:8000/api/settings/relive-api-key
# Expected: {"api_key_set": false, "api_key": ""}

# Nick settings (pick a nick_live_id that exists)
curl -X GET http://localhost:8000/api/nick-lives/1/settings
# Expected: includes host_reply_enabled, host_auto_post_enabled

# Host status
curl -X GET http://localhost:8000/api/nick-lives/1/host/status
# Expected: {"configured": false, "uuid": null, ...}

# Per-nick auto-post templates
curl -X GET http://localhost:8000/api/nick-lives/1/auto-post-templates
# Expected: []

# Auto-post status
curl -X GET http://localhost:8000/api/nick-lives/1/auto-post/status
# Expected: {"running": false}
```

- [ ] **Step 3: Start frontend and verify UI**

```bash
cd frontend && npm run dev
```

- Open LiveScan page
- Verify config button (gear icon) appears on each nick row
- Click config button → modal opens with 4 tabs
- Settings page should show relive key input, no more template sections

- [ ] **Step 4: Test host credentials flow (if relive key available)**

1. Set relive API key on Settings page
2. Open nick config modal → Host Config tab
3. Enter proxy (optional)
4. Click "Get Credentials"
5. Verify UUID shows up

- [ ] **Step 5: Test auto-post flow**

1. Open nick config modal → Auto-post tab
2. Add 2 templates with short intervals (10-15s for testing)
3. Start scan for the nick
4. Click "Start" auto-post
5. Verify messages appear in live stream
6. Click "Stop"

- [ ] **Step 6: Commit any fixes**

```bash
git add -A
git commit -m "fix: integration fixes for host comment feature"
```
