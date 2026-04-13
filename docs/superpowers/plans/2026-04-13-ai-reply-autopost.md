# AI Reply, Auto-reply & Auto-post Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm OpenAI config, reply templates, auto-post templates (shared) và toggles bật/tắt AI reply / auto-reply / auto-post (per-nick) vào app quét comment Shopee Live.

**Architecture:** DB-for-config + memory-for-runtime. 4 bảng SQLite mới lưu cấu hình persistent. Runtime state (loops đang chạy, scan tasks) vẫn in-memory. Scanner mở rộng sang pub/sub để nhiều consumer nhận comment đồng thời.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic v2, OpenAI Python SDK, asyncio, React + Ant Design

---

## File Map

**Tạo mới:**
- `backend/app/models/settings.py` — 4 SQLAlchemy models mới
- `backend/app/schemas/settings.py` — Pydantic schemas cho settings API
- `backend/app/services/settings_service.py` — CRUD + memory cache
- `backend/app/services/ai_reply_service.py` — OpenAI integration
- `backend/app/routers/settings.py` — /api/settings router
- `backend/tests/__init__.py` — test package
- `backend/tests/test_settings_service.py` — unit tests settings service
- `backend/tests/test_ai_reply_service.py` — unit tests AI service
- `frontend/src/api/settings.ts` — API client cho settings
- `frontend/src/pages/Settings.tsx` — trang cấu hình

**Sửa đổi:**
- `backend/app/services/comment_scanner.py` — pub/sub queue (nhiều subscriber)
- `backend/app/services/live_moderator.py` — auto-reply loop + auto-post loop
- `backend/app/routers/nick_live.py` — thêm /settings endpoint
- `backend/app/main.py` — đăng ký router mới, load cache khi startup
- `backend/requirements.txt` — thêm `openai`
- `frontend/src/App.tsx` — thêm route /settings
- `frontend/src/components/Layout.tsx` — thêm menu item Settings
- `frontend/src/pages/LiveScan.tsx` — thêm card Cài đặt tự động

---

## Task 1: DB Models mới

**Files:**
- Create: `backend/app/models/settings.py`
- Modify: `backend/app/database.py` (import models để init_db tạo bảng)

- [ ] **Step 1: Tạo file models/settings.py**

```python
# backend/app/models/settings.py
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ReplyTemplate(Base):
    __tablename__ = "reply_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class AutoPostTemplate(Base):
    __tablename__ = "auto_post_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    min_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    max_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class NickLiveSetting(Base):
    __tablename__ = "nick_live_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nick_live_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    ai_reply_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_reply_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_post_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

- [ ] **Step 2: Import models vào database.py để init_db nhận ra bảng mới**

Thêm dòng import vào cuối `backend/app/database.py`:

```python
# Thêm vào cuối file, sau class Base
def init_db():
    # Import all models so SQLAlchemy knows about them
    from app.models import nick_live  # noqa: F401
    from app.models import settings  # noqa: F401
    Base.metadata.create_all(bind=engine)
```

Thay hàm `init_db()` hiện tại (dòng 27-28) bằng đoạn trên.

- [ ] **Step 3: Chạy server để kiểm tra bảng được tạo**

```bash
cd backend
python -c "from app.database import init_db; init_db(); print('OK')"
```

Expected output: `OK` (không lỗi). Kiểm tra file `database.db` có 4 bảng mới:

```bash
python -c "
import sqlite3
conn = sqlite3.connect('database.db')
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
print([t[0] for t in tables])
"
```

Expected: `['nick_lives', 'app_settings', 'reply_templates', 'auto_post_templates', 'nick_live_settings']`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/settings.py backend/app/database.py
git commit -m "feat: add DB models for settings, templates, nick_live_settings"
```

---

## Task 2: Pydantic Schemas cho Settings

**Files:**
- Create: `backend/app/schemas/settings.py`

- [ ] **Step 1: Tạo file schemas/settings.py**

```python
# backend/app/schemas/settings.py
from pydantic import BaseModel, Field


class OpenAIConfigUpdate(BaseModel):
    api_key: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=100)


class OpenAIConfigResponse(BaseModel):
    api_key_set: bool
    model: str | None


class SystemPromptUpdate(BaseModel):
    prompt: str = Field(max_length=10000)


class SystemPromptResponse(BaseModel):
    prompt: str


class ReplyTemplateCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class ReplyTemplateResponse(BaseModel):
    id: int
    content: str
    model_config = {"from_attributes": True}


class AutoPostTemplateCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    min_interval_seconds: int = Field(ge=10, le=86400, default=60)
    max_interval_seconds: int = Field(ge=10, le=86400, default=300)


class AutoPostTemplateUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    min_interval_seconds: int | None = Field(default=None, ge=10, le=86400)
    max_interval_seconds: int | None = Field(default=None, ge=10, le=86400)


class AutoPostTemplateResponse(BaseModel):
    id: int
    content: str
    min_interval_seconds: int
    max_interval_seconds: int
    model_config = {"from_attributes": True}


class NickLiveSettingsUpdate(BaseModel):
    ai_reply_enabled: bool | None = None
    auto_reply_enabled: bool | None = None
    auto_post_enabled: bool | None = None


class NickLiveSettingsResponse(BaseModel):
    nick_live_id: int
    ai_reply_enabled: bool
    auto_reply_enabled: bool
    auto_post_enabled: bool
    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/settings.py
git commit -m "feat: add Pydantic schemas for settings API"
```

---

## Task 3: Settings Service (CRUD + Cache)

**Files:**
- Create: `backend/app/services/settings_service.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_settings_service.py`

- [ ] **Step 1: Tạo tests/__init__.py**

```python
# backend/tests/__init__.py
```

(file rỗng)

- [ ] **Step 2: Viết tests trước**

```python
# backend/tests/test_settings_service.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.settings import AppSetting, ReplyTemplate, AutoPostTemplate


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # Import all models
    from app.models import nick_live  # noqa
    from app.models import settings  # noqa
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_set_and_get_setting(db):
    from app.services.settings_service import SettingsService
    svc = SettingsService(db)
    svc.set_setting("openai_api_key", "sk-test")
    assert svc.get_setting("openai_api_key") == "sk-test"


def test_get_setting_missing_returns_none(db):
    from app.services.settings_service import SettingsService
    svc = SettingsService(db)
    assert svc.get_setting("nonexistent") is None


def test_get_openai_config_api_key_set(db):
    from app.services.settings_service import SettingsService
    svc = SettingsService(db)
    svc.set_setting("openai_api_key", "sk-real")
    svc.set_setting("openai_model", "gpt-4o")
    config = svc.get_openai_config()
    assert config["api_key_set"] is True
    assert config["model"] == "gpt-4o"


def test_reply_template_crud(db):
    from app.services.settings_service import SettingsService
    svc = SettingsService(db)
    tmpl = svc.create_reply_template("Cảm ơn bạn!")
    assert tmpl.id is not None
    assert tmpl.content == "Cảm ơn bạn!"
    templates = svc.get_reply_templates()
    assert len(templates) == 1
    svc.delete_reply_template(tmpl.id)
    assert len(svc.get_reply_templates()) == 0


def test_auto_post_template_crud(db):
    from app.services.settings_service import SettingsService
    svc = SettingsService(db)
    tmpl = svc.create_auto_post_template("Mua ngay!", min_interval=30, max_interval=120)
    assert tmpl.min_interval_seconds == 30
    updated = svc.update_auto_post_template(tmpl.id, content="Săn sale!")
    assert updated.content == "Săn sale!"
    svc.delete_auto_post_template(tmpl.id)
    assert len(svc.get_auto_post_templates()) == 0


def test_nick_live_settings_default_all_off(db):
    from app.services.settings_service import SettingsService
    svc = SettingsService(db)
    settings = svc.get_or_create_nick_settings(nick_live_id=42)
    assert settings.ai_reply_enabled is False
    assert settings.auto_reply_enabled is False
    assert settings.auto_post_enabled is False


def test_nick_live_settings_update(db):
    from app.services.settings_service import SettingsService
    svc = SettingsService(db)
    svc.get_or_create_nick_settings(nick_live_id=1)
    updated = svc.update_nick_settings(nick_live_id=1, ai_reply_enabled=True)
    assert updated.ai_reply_enabled is True
    assert updated.auto_reply_enabled is False  # unchanged
```

- [ ] **Step 3: Chạy tests — phải FAIL**

```bash
cd backend
python -m pytest tests/test_settings_service.py -v
```

Expected: `ImportError: cannot import name 'SettingsService'`

- [ ] **Step 4: Implement SettingsService**

```python
# backend/app/services/settings_service.py
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.settings import AppSetting, AutoPostTemplate, NickLiveSetting, ReplyTemplate

logger = logging.getLogger(__name__)


class SettingsService:
    def __init__(self, db: Session) -> None:
        self._db = db

    # --- App settings (key-value) ---

    def get_setting(self, key: str) -> str | None:
        row = self._db.query(AppSetting).filter(AppSetting.key == key).first()
        return row.value if row else None

    def set_setting(self, key: str, value: str) -> None:
        row = self._db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            row.value = value
        else:
            row = AppSetting(key=key, value=value)
            self._db.add(row)
        self._db.commit()

    def get_openai_config(self) -> dict[str, Any]:
        api_key = self.get_setting("openai_api_key")
        model = self.get_setting("openai_model")
        return {
            "api_key_set": bool(api_key),
            "model": model,
        }

    def get_openai_api_key(self) -> str | None:
        return self.get_setting("openai_api_key")

    def get_system_prompt(self) -> str:
        return self.get_setting("ai_system_prompt") or ""

    # --- Reply templates ---

    def get_reply_templates(self) -> list[ReplyTemplate]:
        return self._db.query(ReplyTemplate).order_by(ReplyTemplate.created_at).all()

    def create_reply_template(self, content: str) -> ReplyTemplate:
        tmpl = ReplyTemplate(content=content)
        self._db.add(tmpl)
        self._db.commit()
        self._db.refresh(tmpl)
        return tmpl

    def delete_reply_template(self, template_id: int) -> bool:
        tmpl = self._db.query(ReplyTemplate).filter(ReplyTemplate.id == template_id).first()
        if not tmpl:
            return False
        self._db.delete(tmpl)
        self._db.commit()
        return True

    # --- Auto-post templates ---

    def get_auto_post_templates(self) -> list[AutoPostTemplate]:
        return self._db.query(AutoPostTemplate).order_by(AutoPostTemplate.created_at).all()

    def create_auto_post_template(
        self, content: str, min_interval: int = 60, max_interval: int = 300
    ) -> AutoPostTemplate:
        tmpl = AutoPostTemplate(
            content=content,
            min_interval_seconds=min_interval,
            max_interval_seconds=max_interval,
        )
        self._db.add(tmpl)
        self._db.commit()
        self._db.refresh(tmpl)
        return tmpl

    def update_auto_post_template(
        self,
        template_id: int,
        content: str | None = None,
        min_interval: int | None = None,
        max_interval: int | None = None,
    ) -> AutoPostTemplate | None:
        tmpl = self._db.query(AutoPostTemplate).filter(AutoPostTemplate.id == template_id).first()
        if not tmpl:
            return None
        if content is not None:
            tmpl.content = content
        if min_interval is not None:
            tmpl.min_interval_seconds = min_interval
        if max_interval is not None:
            tmpl.max_interval_seconds = max_interval
        self._db.commit()
        self._db.refresh(tmpl)
        return tmpl

    def delete_auto_post_template(self, template_id: int) -> bool:
        tmpl = self._db.query(AutoPostTemplate).filter(AutoPostTemplate.id == template_id).first()
        if not tmpl:
            return False
        self._db.delete(tmpl)
        self._db.commit()
        return True

    # --- Nick live settings ---

    def get_or_create_nick_settings(self, nick_live_id: int) -> NickLiveSetting:
        row = self._db.query(NickLiveSetting).filter(
            NickLiveSetting.nick_live_id == nick_live_id
        ).first()
        if not row:
            row = NickLiveSetting(nick_live_id=nick_live_id)
            self._db.add(row)
            self._db.commit()
            self._db.refresh(row)
        return row

    def update_nick_settings(
        self,
        nick_live_id: int,
        ai_reply_enabled: bool | None = None,
        auto_reply_enabled: bool | None = None,
        auto_post_enabled: bool | None = None,
    ) -> NickLiveSetting:
        row = self.get_or_create_nick_settings(nick_live_id)
        if ai_reply_enabled is not None:
            row.ai_reply_enabled = ai_reply_enabled
        if auto_reply_enabled is not None:
            row.auto_reply_enabled = auto_reply_enabled
        if auto_post_enabled is not None:
            row.auto_post_enabled = auto_post_enabled
        self._db.commit()
        self._db.refresh(row)
        return row
```

- [ ] **Step 5: Chạy tests — phải PASS**

```bash
cd backend
python -m pytest tests/test_settings_service.py -v
```

Expected: `7 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/settings_service.py backend/tests/
git commit -m "feat: add SettingsService with CRUD for settings, templates, nick settings"
```

---

## Task 4: Settings API Router

**Files:**
- Create: `backend/app/routers/settings.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Tạo routers/settings.py**

```python
# backend/app/routers/settings.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_api_key
from app.schemas.settings import (
    AutoPostTemplateCreate,
    AutoPostTemplateResponse,
    AutoPostTemplateUpdate,
    OpenAIConfigResponse,
    OpenAIConfigUpdate,
    ReplyTemplateCreate,
    ReplyTemplateResponse,
    SystemPromptResponse,
    SystemPromptUpdate,
)
from app.services.settings_service import SettingsService

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(require_api_key)],
)


# --- OpenAI config ---

@router.get("/openai", response_model=OpenAIConfigResponse)
def get_openai_config(db: Session = Depends(get_db)) -> OpenAIConfigResponse:
    svc = SettingsService(db)
    config = svc.get_openai_config()
    return OpenAIConfigResponse(**config)


@router.put("/openai")
def update_openai_config(
    payload: OpenAIConfigUpdate, db: Session = Depends(get_db)
) -> dict:
    svc = SettingsService(db)
    svc.set_setting("openai_api_key", payload.api_key)
    svc.set_setting("openai_model", payload.model)
    return {"status": "saved"}


# --- System prompt ---

@router.get("/system-prompt", response_model=SystemPromptResponse)
def get_system_prompt(db: Session = Depends(get_db)) -> SystemPromptResponse:
    svc = SettingsService(db)
    return SystemPromptResponse(prompt=svc.get_system_prompt())


@router.put("/system-prompt")
def update_system_prompt(
    payload: SystemPromptUpdate, db: Session = Depends(get_db)
) -> dict:
    svc = SettingsService(db)
    svc.set_setting("ai_system_prompt", payload.prompt)
    return {"status": "saved"}


# --- Reply templates ---

@router.get("/reply-templates", response_model=list[ReplyTemplateResponse])
def list_reply_templates(db: Session = Depends(get_db)) -> list:
    return SettingsService(db).get_reply_templates()


@router.post("/reply-templates", response_model=ReplyTemplateResponse)
def create_reply_template(
    payload: ReplyTemplateCreate, db: Session = Depends(get_db)
):
    return SettingsService(db).create_reply_template(payload.content)


@router.delete("/reply-templates/{template_id}")
def delete_reply_template(template_id: int, db: Session = Depends(get_db)) -> dict:
    if not SettingsService(db).delete_reply_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"detail": "Deleted"}


# --- Auto-post templates ---

@router.get("/auto-post-templates", response_model=list[AutoPostTemplateResponse])
def list_auto_post_templates(db: Session = Depends(get_db)) -> list:
    return SettingsService(db).get_auto_post_templates()


@router.post("/auto-post-templates", response_model=AutoPostTemplateResponse)
def create_auto_post_template(
    payload: AutoPostTemplateCreate, db: Session = Depends(get_db)
):
    return SettingsService(db).create_auto_post_template(
        payload.content, payload.min_interval_seconds, payload.max_interval_seconds
    )


@router.put("/auto-post-templates/{template_id}", response_model=AutoPostTemplateResponse)
def update_auto_post_template(
    template_id: int, payload: AutoPostTemplateUpdate, db: Session = Depends(get_db)
):
    result = SettingsService(db).update_auto_post_template(
        template_id,
        content=payload.content,
        min_interval=payload.min_interval_seconds,
        max_interval=payload.max_interval_seconds,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Template not found")
    return result


@router.delete("/auto-post-templates/{template_id}")
def delete_auto_post_template(template_id: int, db: Session = Depends(get_db)) -> dict:
    if not SettingsService(db).delete_auto_post_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"detail": "Deleted"}
```

- [ ] **Step 2: Đăng ký router trong main.py**

Sửa `backend/app/main.py` — thêm import và `include_router`:

```python
# backend/app/main.py
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.routers.nick_live import router as nick_live_router
from app.routers.settings import router as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


is_dev = os.getenv("ENV", "development") == "development"

app = FastAPI(
    title="App Rep Comment",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if is_dev else None,
    redoc_url="/redoc" if is_dev else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-API-Key"],
)

app.include_router(nick_live_router)
app.include_router(settings_router)


@app.get("/api/health")
@app.get("/health")
def health_check():
    return {"status": "ok"}
```

- [ ] **Step 3: Kiểm tra server khởi động và docs**

```bash
cd backend
uvicorn app.main:app --reload
```

Mở `http://localhost:8000/docs`, kiểm tra có nhóm `settings` với tất cả endpoints.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/settings.py backend/app/main.py
git commit -m "feat: add /api/settings router for OpenAI config, templates"
```

---

## Task 5: Scanner Pub/Sub (nhiều subscriber)

**Files:**
- Modify: `backend/app/services/comment_scanner.py`

- [ ] **Step 1: Mở rộng CommentScanner để support nhiều subscriber queue**

Thay toàn bộ `backend/app/services/comment_scanner.py`:

```python
# backend/app/services/comment_scanner.py
import asyncio
import logging
import time
from collections import defaultdict

from app.services.shopee_api import get_comments

logger = logging.getLogger(__name__)


class CommentScanner:
    """Manages background comment polling tasks for multiple nick lives.

    Supports multiple queue subscribers per nick (pub/sub pattern).
    """

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}
        self._comments: dict[int, list] = defaultdict(list)
        self._seen_ids: dict[int, set] = defaultdict(set)
        self._session_ids: dict[int, int] = {}
        # pub/sub: nick_live_id -> list of subscriber queues
        self._subscribers: dict[int, list[asyncio.Queue]] = defaultdict(list)

    def is_scanning(self, nick_live_id: int) -> bool:
        return nick_live_id in self._tasks and not self._tasks[nick_live_id].done()

    def get_status(self, nick_live_id: int) -> dict:
        return {
            "is_scanning": self.is_scanning(nick_live_id),
            "session_id": self._session_ids.get(nick_live_id),
            "comment_count": len(self._comments.get(nick_live_id, [])),
        }

    def get_comments(self, nick_live_id: int) -> list:
        return list(self._comments.get(nick_live_id, []))

    def subscribe(self, nick_live_id: int) -> asyncio.Queue:
        """Register a new subscriber queue. Returns the queue."""
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers[nick_live_id].append(q)
        return q

    def unsubscribe(self, nick_live_id: int, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue."""
        subscribers = self._subscribers.get(nick_live_id, [])
        if queue in subscribers:
            subscribers.remove(queue)

    # Keep get_queue for SSE backward compatibility (creates+subscribes)
    def get_queue(self, nick_live_id: int) -> asyncio.Queue:
        return self.subscribe(nick_live_id)

    def start(
        self,
        nick_live_id: int,
        session_id: int,
        cookies: str,
        poll_interval: float = 2.0,
    ) -> None:
        if self.is_scanning(nick_live_id):
            return

        self._session_ids[nick_live_id] = session_id
        self._comments[nick_live_id] = []
        self._seen_ids[nick_live_id] = set()
        self._subscribers[nick_live_id] = []

        task = asyncio.create_task(
            self._poll_loop(nick_live_id, session_id, cookies, poll_interval)
        )
        self._tasks[nick_live_id] = task

    def stop(self, nick_live_id: int) -> None:
        task = self._tasks.get(nick_live_id)
        if task and not task.done():
            task.cancel()
        self._tasks.pop(nick_live_id, None)
        self._session_ids.pop(nick_live_id, None)
        # Signal all subscribers that stream ended
        for q in self._subscribers.get(nick_live_id, []):
            q.put_nowait(None)
        self._subscribers[nick_live_id] = []

    async def _poll_loop(
        self,
        nick_live_id: int,
        session_id: int,
        cookies: str,
        poll_interval: float,
    ) -> None:
        last_ts = int(time.time())
        logger.info(f"Started scanning nick_live={nick_live_id} session={session_id}")

        try:
            while True:
                try:
                    items = await get_comments(cookies, session_id, last_ts)
                    for c in items:
                        cid = (
                            c.get("id")
                            or c.get("msg_id")
                            or c.get("msgId")
                            or f"{c.get('timestamp')}_{c.get('content')}"
                        )
                        cid = str(cid)
                        if cid not in self._seen_ids[nick_live_id]:
                            self._seen_ids[nick_live_id].add(cid)
                            self._comments[nick_live_id].append(c)
                            # Broadcast to all subscribers
                            for q in self._subscribers.get(nick_live_id, []):
                                await q.put(c)

                    if items:
                        last_ts = int(time.time())

                except Exception as e:
                    logger.error(f"Poll error for nick_live={nick_live_id}: {e}")

                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            logger.info(f"Stopped scanning nick_live={nick_live_id}")


# Singleton instance
scanner = CommentScanner()
```

- [ ] **Step 2: Kiểm tra SSE streaming vẫn hoạt động**

Start server và dùng existing Live Scan UI — SSE stream comments vẫn chạy bình thường (không break change vì `get_queue()` vẫn tồn tại).

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/comment_scanner.py
git commit -m "feat: extend CommentScanner to pub/sub (multiple subscribers)"
```

---

## Task 6: AI Reply Service

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/app/services/ai_reply_service.py`
- Create: `backend/tests/test_ai_reply_service.py`

- [ ] **Step 1: Thêm openai vào requirements.txt**

Thêm vào cuối `backend/requirements.txt`:

```
openai>=1.0.0
```

Cài:

```bash
cd backend
pip install openai
```

- [ ] **Step 2: Viết tests**

```python
# backend/tests/test_ai_reply_service.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_generate_reply_calls_openai():
    from app.services.ai_reply_service import generate_reply

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Cảm ơn bạn đã hỏi!"))]

    with patch("app.services.ai_reply_service.AsyncOpenAI") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await generate_reply(
            api_key="sk-test",
            model="gpt-4o",
            system_prompt="Bạn là nhân viên CSKH Shopee Live.",
            comment_text="Giá bao nhiêu vậy?",
            guest_name="user123",
        )

    assert result == "Cảm ơn bạn đã hỏi!"


@pytest.mark.asyncio
async def test_generate_reply_returns_fallback_on_error():
    from app.services.ai_reply_service import generate_reply

    with patch("app.services.ai_reply_service.AsyncOpenAI") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API error"))

        result = await generate_reply(
            api_key="sk-test",
            model="gpt-4o",
            system_prompt="...",
            comment_text="Hỏi gì đó",
            guest_name="user",
        )

    assert result is None
```

- [ ] **Step 3: Chạy tests — phải FAIL**

```bash
cd backend
python -m pytest tests/test_ai_reply_service.py -v
```

Expected: `ImportError: cannot import name 'generate_reply'`

- [ ] **Step 4: Implement ai_reply_service.py**

```python
# backend/app/services/ai_reply_service.py
import logging

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


async def generate_reply(
    api_key: str,
    model: str,
    system_prompt: str,
    comment_text: str,
    guest_name: str,
) -> str | None:
    """Call OpenAI to generate reply text for a guest comment.

    Returns the reply text (to be appended after @guest_name), or None on error.
    """
    try:
        client = AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Khách hàng {guest_name} bình luận: {comment_text}",
                },
            ],
            max_tokens=200,
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI reply generation failed: {e}")
        return None
```

- [ ] **Step 5: Chạy tests — phải PASS**

```bash
cd backend
pip install pytest-asyncio
python -m pytest tests/test_ai_reply_service.py -v
```

Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/app/services/ai_reply_service.py backend/tests/test_ai_reply_service.py
git commit -m "feat: add AI reply service using OpenAI Chat Completions"
```

---

## Task 7: Auto-reply Loop trong Moderator

**Files:**
- Modify: `backend/app/services/live_moderator.py`

- [ ] **Step 1: Thêm auto-reply loop vào ShopeeLiveModerator**

Thêm vào cuối class `ShopeeLiveModerator` (trước dòng `# Singleton instance`):

```python
    # --- Auto-reply loop ---

    def start_auto_reply_loop(
        self,
        nick_live_id: int,
        live_session_id: int,
    ) -> None:
        """Start background task that auto-replies to new comments."""
        if f"auto_reply_{nick_live_id}" in self._loop_tasks:
            return  # already running

        task = asyncio.create_task(
            self._auto_reply_loop(nick_live_id, live_session_id)
        )
        self._loop_tasks[f"auto_reply_{nick_live_id}"] = task
        logger.info(f"Auto-reply loop started for nick_live={nick_live_id}")

    def stop_auto_reply_loop(self, nick_live_id: int) -> None:
        key = f"auto_reply_{nick_live_id}"
        task = self._loop_tasks.pop(key, None)
        if task and not task.done():
            task.cancel()
        logger.info(f"Auto-reply loop stopped for nick_live={nick_live_id}")

    async def _auto_reply_loop(
        self,
        nick_live_id: int,
        live_session_id: int,
    ) -> None:
        from app.database import SessionLocal
        from app.services.comment_scanner import scanner
        from app.services.settings_service import SettingsService
        from app.services.ai_reply_service import generate_reply
        import random

        queue = scanner.subscribe(nick_live_id)
        try:
            while True:
                comment = await queue.get()
                if comment is None:
                    break

                db = SessionLocal()
                try:
                    svc = SettingsService(db)
                    nick_settings = svc.get_or_create_nick_settings(nick_live_id)

                username = (
                    comment.get("username")
                    or comment.get("userName")
                    or comment.get("nick_name")
                    or comment.get("nickname")
                    or "Unknown"
                )
                user_id = comment.get("streamerId") or comment.get("userId") or 0
                comment_text = (
                    comment.get("content")
                    or comment.get("comment")
                    or comment.get("message")
                    or comment.get("msg")
                    or ""
                )

                if nick_settings.ai_reply_enabled:
                    api_key = svc.get_openai_api_key()
                    model = svc.get_setting("openai_model") or "gpt-4o"
                    system_prompt = svc.get_system_prompt()
                    if api_key:
                        reply_text = await generate_reply(
                            api_key, model, system_prompt, comment_text, username
                        )
                    else:
                        reply_text = None
                else:
                    templates = svc.get_reply_templates()
                    reply_text = random.choice(templates).content if templates else None

                    if reply_text:
                        await self.send_reply(
                            nick_live_id, live_session_id, username, user_id, reply_text
                        )
                finally:
                    db.close()
        except asyncio.CancelledError:
            pass
        finally:
            scanner.unsubscribe(nick_live_id, queue)
```

Cũng thêm `_loop_tasks: dict[str, asyncio.Task] = {}` vào `__init__`:

```python
    def __init__(self) -> None:
        self._configs: dict[int, dict[str, Any]] = {}
        self._loop_tasks: dict[str, asyncio.Task] = {}
```

- [ ] **Step 2: Kiểm tra không có lỗi import**

```bash
cd backend
python -c "from app.services.live_moderator import moderator; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/live_moderator.py
git commit -m "feat: add auto-reply loop to ShopeeLiveModerator"
```

---

## Task 8: Auto-post Loop trong Moderator

**Files:**
- Modify: `backend/app/services/live_moderator.py`

- [ ] **Step 1: Thêm generate_post_body và auto-post loop**

Thêm method `generate_post_body` vào class (sau `generate_reply_body`):

```python
    def generate_post_body(
        self,
        nick_live_id: int,
        content: str,
    ) -> dict[str, Any] | None:
        """Build request body for posting a plain message (no @mention)."""
        config = self._configs.get(nick_live_id)
        if not config:
            return None

        import json as _json
        inner_content = {
            "content": content,
            "content_v2": content,
            "extra_info": {"feedback_transparent": ""},
            "type": 102,
        }
        return {
            "content": _json.dumps(inner_content, ensure_ascii=False),
            "send_ts": int(time.time() * 1000),
            "usersig": config["usersig"],
            "uuid": config["uuid"],
        }
```

Thêm auto-post loop methods vào class:

```python
    # --- Auto-post loop ---

    def start_auto_post_loop(self, nick_live_id: int) -> None:
        """Start background tasks that post scheduled messages."""
        key = f"auto_post_{nick_live_id}"
        if key in self._loop_tasks:
            return

        task = asyncio.create_task(
            self._auto_post_loop(nick_live_id)
        )
        self._loop_tasks[key] = task
        logger.info(f"Auto-post loop started for nick_live={nick_live_id}")

    def stop_auto_post_loop(self, nick_live_id: int) -> None:
        key = f"auto_post_{nick_live_id}"
        task = self._loop_tasks.pop(key, None)
        if task and not task.done():
            task.cancel()
        logger.info(f"Auto-post loop stopped for nick_live={nick_live_id}")

    async def _auto_post_loop(self, nick_live_id: int) -> None:
        import asyncio as _asyncio
        import random as _random

        from app.database import SessionLocal
        from app.services.comment_scanner import scanner
        from app.services.settings_service import SettingsService

        try:
            while True:
                db = SessionLocal()
                try:
                    svc = SettingsService(db)
                    templates = svc.get_auto_post_templates()
                finally:
                    db.close()
                if not templates:
                    await _asyncio.sleep(30)
                    continue

                for tmpl in templates:
                    wait_secs = _random.uniform(
                        tmpl.min_interval_seconds, tmpl.max_interval_seconds
                    )
                    await _asyncio.sleep(wait_secs)

                    status = scanner.get_status(nick_live_id)
                    if not status["is_scanning"] or not status.get("session_id"):
                        continue

                    live_session_id = status["session_id"]
                    body = self.generate_post_body(nick_live_id, tmpl.content)
                    if not body:
                        continue

                    url = f"https://{_REQUIRED_HOST}/api/v1/session/{live_session_id}/message"
                    config = self._configs.get(nick_live_id)
                    if not config:
                        continue

                    try:
                        async with httpx.AsyncClient() as client:
                            resp = await client.post(
                                url, headers=config["headers"], json=body, timeout=10.0
                            )
                            if resp.status_code == 200:
                                resp_data = resp.json()
                                if resp_data.get("err_code") == 0:
                                    logger.info(f"Auto-posted for nick_live={nick_live_id}: {tmpl.content[:50]}")
                                else:
                                    logger.warning(f"Auto-post failed err_code={resp_data.get('err_code')}")
                            else:
                                logger.warning(f"Auto-post HTTP {resp.status_code}")
                    except Exception as e:
                        logger.error(f"Auto-post error: {e}")

        except asyncio.CancelledError:
            pass
```

- [ ] **Step 2: Kiểm tra import**

```bash
cd backend
python -c "from app.services.live_moderator import moderator; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/live_moderator.py
git commit -m "feat: add auto-post loop and generate_post_body to ShopeeLiveModerator"
```

---

## Task 9: Per-nick Settings API

**Files:**
- Modify: `backend/app/routers/nick_live.py`

- [ ] **Step 1: Thêm import schemas và endpoint /settings vào routers/nick_live.py**

Thêm imports ở đầu file (sau các import hiện có):

```python
from app.schemas.settings import NickLiveSettingsResponse, NickLiveSettingsUpdate
from app.services.settings_service import SettingsService
```

Thêm 2 endpoints mới ở cuối router (trước EOF):

```python
# --- Per-nick automation settings ---


@router.get("/{nick_live_id}/settings", response_model=NickLiveSettingsResponse)
def get_nick_settings(
    nick_live_id: int, db: Session = Depends(get_db)
) -> NickLiveSettingsResponse:
    """Get automation toggles for a nick live."""
    nick = db.query(NickLive).filter(NickLive.id == nick_live_id).first()
    if not nick:
        raise HTTPException(status_code=404, detail="NickLive not found")
    row = SettingsService(db).get_or_create_nick_settings(nick_live_id)
    return NickLiveSettingsResponse(
        nick_live_id=nick_live_id,
        ai_reply_enabled=row.ai_reply_enabled,
        auto_reply_enabled=row.auto_reply_enabled,
        auto_post_enabled=row.auto_post_enabled,
    )


@router.put("/{nick_live_id}/settings", response_model=NickLiveSettingsResponse)
async def update_nick_settings(
    nick_live_id: int,
    payload: NickLiveSettingsUpdate,
    db: Session = Depends(get_db),
) -> NickLiveSettingsResponse:
    """Update automation toggles. Starts/stops loops automatically."""
    nick = db.query(NickLive).filter(NickLive.id == nick_live_id).first()
    if not nick:
        raise HTTPException(status_code=404, detail="NickLive not found")

    updated = SettingsService(db).update_nick_settings(
        nick_live_id,
        ai_reply_enabled=payload.ai_reply_enabled,
        auto_reply_enabled=payload.auto_reply_enabled,
        auto_post_enabled=payload.auto_post_enabled,
    )

    scan_status = scanner.get_status(nick_live_id)
    is_active = scan_status["is_scanning"] and scan_status.get("session_id")
    live_session_id = scan_status.get("session_id")

    # Start/stop auto-reply loop
    if payload.auto_reply_enabled is not None:
        if payload.auto_reply_enabled and is_active and moderator.has_config(nick_live_id):
            moderator.start_auto_reply_loop(nick_live_id, live_session_id)
        elif not payload.auto_reply_enabled:
            moderator.stop_auto_reply_loop(nick_live_id)

    # Start/stop auto-post loop
    if payload.auto_post_enabled is not None:
        if payload.auto_post_enabled and is_active and moderator.has_config(nick_live_id):
            moderator.start_auto_post_loop(nick_live_id)
        elif not payload.auto_post_enabled:
            moderator.stop_auto_post_loop(nick_live_id)

    return NickLiveSettingsResponse(
        nick_live_id=nick_live_id,
        ai_reply_enabled=updated.ai_reply_enabled,
        auto_reply_enabled=updated.auto_reply_enabled,
        auto_post_enabled=updated.auto_post_enabled,
    )
```

- [ ] **Step 2: Kiểm tra server và docs**

```bash
uvicorn app.main:app --reload
```

Mở `http://localhost:8000/docs`, kiểm tra có `GET/PUT /api/nick-lives/{nick_live_id}/settings`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/nick_live.py
git commit -m "feat: add GET/PUT /api/nick-lives/{id}/settings for automation toggles"
```

---

## Task 10: Frontend API Client

**Files:**
- Create: `frontend/src/api/settings.ts`

- [ ] **Step 1: Tạo settings.ts**

```typescript
// frontend/src/api/settings.ts
import apiClient from "./client";

export interface OpenAIConfig {
  api_key_set: boolean;
  model: string | null;
}

export interface SystemPrompt {
  prompt: string;
}

export interface ReplyTemplate {
  id: number;
  content: string;
}

export interface AutoPostTemplate {
  id: number;
  content: string;
  min_interval_seconds: number;
  max_interval_seconds: number;
}

export interface NickLiveSettings {
  nick_live_id: number;
  ai_reply_enabled: boolean;
  auto_reply_enabled: boolean;
  auto_post_enabled: boolean;
}

// --- OpenAI ---

export async function getOpenAIConfig(): Promise<OpenAIConfig> {
  const res = await apiClient.get("/settings/openai");
  return res.data;
}

export async function updateOpenAIConfig(api_key: string, model: string): Promise<void> {
  await apiClient.put("/settings/openai", { api_key, model });
}

// --- System prompt ---

export async function getSystemPrompt(): Promise<SystemPrompt> {
  const res = await apiClient.get("/settings/system-prompt");
  return res.data;
}

export async function updateSystemPrompt(prompt: string): Promise<void> {
  await apiClient.put("/settings/system-prompt", { prompt });
}

// --- Reply templates ---

export async function getReplyTemplates(): Promise<ReplyTemplate[]> {
  const res = await apiClient.get("/settings/reply-templates");
  return res.data;
}

export async function createReplyTemplate(content: string): Promise<ReplyTemplate> {
  const res = await apiClient.post("/settings/reply-templates", { content });
  return res.data;
}

export async function deleteReplyTemplate(id: number): Promise<void> {
  await apiClient.delete(`/settings/reply-templates/${id}`);
}

// --- Auto-post templates ---

export async function getAutoPostTemplates(): Promise<AutoPostTemplate[]> {
  const res = await apiClient.get("/settings/auto-post-templates");
  return res.data;
}

export async function createAutoPostTemplate(
  content: string,
  min_interval_seconds: number,
  max_interval_seconds: number
): Promise<AutoPostTemplate> {
  const res = await apiClient.post("/settings/auto-post-templates", {
    content,
    min_interval_seconds,
    max_interval_seconds,
  });
  return res.data;
}

export async function updateAutoPostTemplate(
  id: number,
  data: Partial<{ content: string; min_interval_seconds: number; max_interval_seconds: number }>
): Promise<AutoPostTemplate> {
  const res = await apiClient.put(`/settings/auto-post-templates/${id}`, data);
  return res.data;
}

export async function deleteAutoPostTemplate(id: number): Promise<void> {
  await apiClient.delete(`/settings/auto-post-templates/${id}`);
}

// --- Nick live settings ---

export async function getNickLiveSettings(nickLiveId: number): Promise<NickLiveSettings> {
  const res = await apiClient.get(`/nick-lives/${nickLiveId}/settings`);
  return res.data;
}

export async function updateNickLiveSettings(
  nickLiveId: number,
  data: Partial<{ ai_reply_enabled: boolean; auto_reply_enabled: boolean; auto_post_enabled: boolean }>
): Promise<NickLiveSettings> {
  const res = await apiClient.put(`/nick-lives/${nickLiveId}/settings`, data);
  return res.data;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/settings.ts
git commit -m "feat: add frontend API client for settings endpoints"
```

---

## Task 11: Frontend Settings Page

**Files:**
- Create: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Tạo Settings.tsx**

```tsx
// frontend/src/pages/Settings.tsx
import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Card,
  Divider,
  Form,
  Input,
  InputNumber,
  List,
  Select,
  Space,
  Typography,
  message,
} from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import {
  type AutoPostTemplate,
  type ReplyTemplate,
  createAutoPostTemplate,
  createReplyTemplate,
  deleteAutoPostTemplate,
  deleteReplyTemplate,
  getAutoPostTemplates,
  getOpenAIConfig,
  getReplyTemplates,
  getSystemPrompt,
  updateAutoPostTemplate,
  updateOpenAIConfig,
  updateSystemPrompt,
} from "../api/settings";

const { Title, Text } = Typography;
const { TextArea } = Input;

const OPENAI_MODELS = [
  { value: "gpt-4o", label: "GPT-4o" },
  { value: "gpt-4o-mini", label: "GPT-4o Mini" },
  { value: "gpt-3.5-turbo", label: "GPT-3.5 Turbo" },
];

function Settings() {
  // OpenAI
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("gpt-4o");
  const [apiKeySet, setApiKeySet] = useState(false);
  const [openaiLoading, setOpenaiLoading] = useState(false);

  // System prompt
  const [systemPrompt, setSystemPrompt] = useState("");
  const [promptLoading, setPromptLoading] = useState(false);

  // Reply templates
  const [replyTemplates, setReplyTemplates] = useState<ReplyTemplate[]>([]);
  const [newReplyContent, setNewReplyContent] = useState("");
  const [replyLoading, setReplyLoading] = useState(false);

  // Auto-post templates
  const [autoPostTemplates, setAutoPostTemplates] = useState<AutoPostTemplate[]>([]);
  const [newPostContent, setNewPostContent] = useState("");
  const [newPostMin, setNewPostMin] = useState(60);
  const [newPostMax, setNewPostMax] = useState(300);
  const [postLoading, setPostLoading] = useState(false);

  const loadAll = useCallback(async () => {
    try {
      const [oai, prompt, replies, posts] = await Promise.all([
        getOpenAIConfig(),
        getSystemPrompt(),
        getReplyTemplates(),
        getAutoPostTemplates(),
      ]);
      setApiKeySet(oai.api_key_set);
      setModel(oai.model || "gpt-4o");
      setSystemPrompt(prompt.prompt);
      setReplyTemplates(replies);
      setAutoPostTemplates(posts);
    } catch {
      message.error("Không thể tải cài đặt");
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const handleSaveOpenAI = async () => {
    if (!apiKey.trim()) {
      message.error("Nhập API key");
      return;
    }
    setOpenaiLoading(true);
    try {
      await updateOpenAIConfig(apiKey, model);
      message.success("Đã lưu cấu hình OpenAI");
      setApiKey("");
      await loadAll();
    } catch {
      message.error("Lưu thất bại");
    } finally {
      setOpenaiLoading(false);
    }
  };

  const handleSavePrompt = async () => {
    setPromptLoading(true);
    try {
      await updateSystemPrompt(systemPrompt);
      message.success("Đã lưu system prompt");
    } catch {
      message.error("Lưu thất bại");
    } finally {
      setPromptLoading(false);
    }
  };

  const handleAddReplyTemplate = async () => {
    if (!newReplyContent.trim()) return;
    setReplyLoading(true);
    try {
      await createReplyTemplate(newReplyContent);
      setNewReplyContent("");
      const updated = await getReplyTemplates();
      setReplyTemplates(updated);
    } catch {
      message.error("Thêm thất bại");
    } finally {
      setReplyLoading(false);
    }
  };

  const handleDeleteReplyTemplate = async (id: number) => {
    try {
      await deleteReplyTemplate(id);
      setReplyTemplates((prev) => prev.filter((t) => t.id !== id));
    } catch {
      message.error("Xóa thất bại");
    }
  };

  const handleAddAutoPost = async () => {
    if (!newPostContent.trim()) return;
    if (newPostMin > newPostMax) {
      message.error("Min phải nhỏ hơn Max");
      return;
    }
    setPostLoading(true);
    try {
      await createAutoPostTemplate(newPostContent, newPostMin, newPostMax);
      setNewPostContent("");
      setNewPostMin(60);
      setNewPostMax(300);
      const updated = await getAutoPostTemplates();
      setAutoPostTemplates(updated);
    } catch {
      message.error("Thêm thất bại");
    } finally {
      setPostLoading(false);
    }
  };

  const handleDeleteAutoPost = async (id: number) => {
    try {
      await deleteAutoPostTemplate(id);
      setAutoPostTemplates((prev) => prev.filter((t) => t.id !== id));
    } catch {
      message.error("Xóa thất bại");
    }
  };

  const handleUpdateAutoPostInterval = async (
    id: number,
    min_interval_seconds: number,
    max_interval_seconds: number
  ) => {
    try {
      const updated = await updateAutoPostTemplate(id, { min_interval_seconds, max_interval_seconds });
      setAutoPostTemplates((prev) => prev.map((t) => (t.id === id ? updated : t)));
    } catch {
      message.error("Cập nhật thất bại");
    }
  };

  return (
    <div>
      <Title level={3}>Cài đặt</Title>

      {/* OpenAI Config */}
      <Card title="Cấu hình OpenAI" style={{ marginBottom: 16 }}>
        {apiKeySet && (
          <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
            API Key đã được lưu. Nhập key mới để thay thế.
          </Text>
        )}
        <Space direction="vertical" style={{ width: "100%" }}>
          <Input.Password
            placeholder="Nhập OpenAI API Key (sk-...)"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          <Select
            style={{ width: 200 }}
            value={model}
            options={OPENAI_MODELS}
            onChange={setModel}
          />
          <Button type="primary" onClick={handleSaveOpenAI} loading={openaiLoading}>
            Lưu cấu hình OpenAI
          </Button>
        </Space>
      </Card>

      {/* System Prompt */}
      <Card title="System Prompt (Prompt cha cho AI)" style={{ marginBottom: 16 }}>
        <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
          AI sẽ dùng prompt này để trả lời comment của khách hàng.
        </Text>
        <TextArea
          rows={5}
          placeholder="Ví dụ: Bạn là nhân viên CSKH của shop trên Shopee Live. Hãy trả lời ngắn gọn, thân thiện và đúng trọng tâm câu hỏi của khách."
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
        />
        <Button
          type="primary"
          onClick={handleSavePrompt}
          loading={promptLoading}
          style={{ marginTop: 8 }}
        >
          Lưu System Prompt
        </Button>
      </Card>

      {/* Reply Templates */}
      <Card
        title="Reply Templates (Non-AI mode)"
        style={{ marginBottom: 16 }}
        extra={<Text type="secondary">Chọn ngẫu nhiên khi AI tắt</Text>}
      >
        <Space.Compact style={{ width: "100%", marginBottom: 12 }}>
          <Input
            placeholder="Thêm câu reply mới (VD: Cảm ơn bạn đã quan tâm!)"
            value={newReplyContent}
            onChange={(e) => setNewReplyContent(e.target.value)}
            onPressEnter={handleAddReplyTemplate}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleAddReplyTemplate}
            loading={replyLoading}
          >
            Thêm
          </Button>
        </Space.Compact>
        <List
          dataSource={replyTemplates}
          locale={{ emptyText: "Chưa có template nào" }}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button
                  key="del"
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  size="small"
                  onClick={() => handleDeleteReplyTemplate(item.id)}
                />,
              ]}
            >
              <Text>{item.content}</Text>
            </List.Item>
          )}
        />
      </Card>

      {/* Auto-post Templates */}
      <Card
        title="Auto-post Templates (Đăng comment theo lịch)"
        style={{ marginBottom: 16 }}
        extra={<Text type="secondary">Xoay vòng, interval ngẫu nhiên trong khoảng min~max</Text>}
      >
        <Space direction="vertical" style={{ width: "100%", marginBottom: 12 }}>
          <TextArea
            rows={2}
            placeholder="Nội dung comment (VD: Mua ngay giảm 50%! 🔥)"
            value={newPostContent}
            onChange={(e) => setNewPostContent(e.target.value)}
          />
          <Space>
            <Text>Interval:</Text>
            <InputNumber
              min={10}
              max={86400}
              value={newPostMin}
              onChange={(v) => setNewPostMin(v || 60)}
              addonAfter="s min"
            />
            <InputNumber
              min={10}
              max={86400}
              value={newPostMax}
              onChange={(v) => setNewPostMax(v || 300)}
              addonAfter="s max"
            />
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleAddAutoPost}
              loading={postLoading}
            >
              Thêm
            </Button>
          </Space>
        </Space>
        <List
          dataSource={autoPostTemplates}
          locale={{ emptyText: "Chưa có template nào" }}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button
                  key="del"
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  size="small"
                  onClick={() => handleDeleteAutoPost(item.id)}
                />,
              ]}
            >
              <Space direction="vertical" size="small" style={{ flex: 1 }}>
                <Text>{item.content}</Text>
                <Space size="small">
                  <Text type="secondary" style={{ fontSize: 12 }}>Interval:</Text>
                  <InputNumber
                    min={10}
                    size="small"
                    value={item.min_interval_seconds}
                    onChange={(v) =>
                      handleUpdateAutoPostInterval(item.id, v || 10, item.max_interval_seconds)
                    }
                    addonAfter="s"
                  />
                  <Text type="secondary">~</Text>
                  <InputNumber
                    min={10}
                    size="small"
                    value={item.max_interval_seconds}
                    onChange={(v) =>
                      handleUpdateAutoPostInterval(item.id, item.min_interval_seconds, v || 10)
                    }
                    addonAfter="s"
                  />
                </Space>
              </Space>
            </List.Item>
          )}
        />
      </Card>
    </div>
  );
}

export default Settings;
```

- [ ] **Step 2: Thêm route vào App.tsx**

```tsx
// frontend/src/App.tsx
import { Routes, Route } from "react-router-dom";
import AppLayout from "./components/Layout";
import Home from "./pages/Home";
import LiveScan from "./pages/LiveScan";
import Settings from "./pages/Settings";

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Home />} />
        <Route path="/live-scan" element={<LiveScan />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}

export default App;
```

- [ ] **Step 3: Thêm menu item vào Layout.tsx**

```tsx
// frontend/src/components/Layout.tsx
import { Layout, Menu } from "antd";
import { HomeOutlined, CommentOutlined, SettingOutlined } from "@ant-design/icons";
import { Outlet, useNavigate, useLocation } from "react-router-dom";

const { Header, Content, Footer } = Layout;

function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();

  const menuItems = [
    {
      key: "/",
      icon: <HomeOutlined />,
      label: "Trang chủ",
    },
    {
      key: "/live-scan",
      icon: <CommentOutlined />,
      label: "Quét Comment",
    },
    {
      key: "/settings",
      icon: <SettingOutlined />,
      label: "Cài đặt",
    },
  ];

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header style={{ display: "flex", alignItems: "center" }}>
        <div
          style={{
            color: "#fff",
            fontSize: 18,
            fontWeight: 600,
            marginRight: 40,
            whiteSpace: "nowrap",
          }}
        >
          App Rep Comment
        </div>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ flex: 1 }}
        />
      </Header>
      <Content style={{ padding: 24 }}>
        <Outlet />
      </Content>
      <Footer style={{ textAlign: "center" }}>
        App Rep Comment &copy; {new Date().getFullYear()}
      </Footer>
    </Layout>
  );
}

export default AppLayout;
```

- [ ] **Step 4: Kiểm tra UI**

```bash
cd frontend
npm run dev
```

Mở `http://localhost:5173/settings`, kiểm tra 4 card hiển thị đúng.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Settings.tsx frontend/src/App.tsx frontend/src/components/Layout.tsx
git commit -m "feat: add Settings page with OpenAI config, system prompt, templates"
```

---

## Task 12: LiveScan — Card Cài đặt tự động

**Files:**
- Modify: `frontend/src/pages/LiveScan.tsx`
- Modify: `frontend/src/api/nickLive.ts` (xóa console.log)

- [ ] **Step 1: Xóa console.log trong nickLive.ts**

Trong `frontend/src/api/nickLive.ts`, xóa dòng 155-156 và 159-160:

```typescript
// Xóa:
  console.log("[sendModeratorReply] payload →", payload);
// ...
  console.log("[sendModeratorReply] response →", res.data);
```

- [ ] **Step 2: Thêm automation state và handlers vào LiveScan.tsx**

Thêm import ở đầu file (sau import từ `../api/nickLive`):

```typescript
import {
  type NickLiveSettings,
  getNickLiveSettings,
  updateNickLiveSettings,
} from "../api/settings";
```

Thêm state automation (sau `const [replyResults, setReplyResults] = useState...`):

```typescript
  const [nickSettings, setNickSettings] = useState<NickLiveSettings | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(false);
```

Thêm handler load settings (sau `loadModStatus`):

```typescript
  const loadNickSettings = useCallback(async () => {
    if (!selectedId) return;
    try {
      const s = await getNickLiveSettings(selectedId);
      setNickSettings(s);
    } catch {
      setNickSettings(null);
    }
  }, [selectedId]);
```

Thêm vào useEffect khi `selectedId` thay đổi (cạnh `loadModStatus()`):

```typescript
  useEffect(() => {
    if (selectedId) {
      loadModStatus();
      loadNickSettings();
    } else {
      setModStatus(null);
      setNickSettings(null);
    }
  }, [selectedId, loadModStatus, loadNickSettings]);
```

Thêm handler toggle:

```typescript
  const handleToggleSetting = useCallback(
    async (field: "ai_reply_enabled" | "auto_reply_enabled" | "auto_post_enabled", value: boolean) => {
      if (!selectedId) return;
      setSettingsLoading(true);
      try {
        const updated = await updateNickLiveSettings(selectedId, { [field]: value });
        setNickSettings(updated);
        message.success(value ? "Đã bật" : "Đã tắt");
      } catch {
        message.error("Cập nhật thất bại");
      } finally {
        setSettingsLoading(false);
      }
    },
    [selectedId]
  );
```

- [ ] **Step 3: Thêm Card Cài đặt tự động vào JSX**

Thêm import `Switch` và `InfoCircleOutlined` vào imports từ `antd`:

```typescript
import {
  Card, Button, Input, Avatar, Row, Col, Table, Alert, Spin, Badge,
  Tag, Space, Typography, Popconfirm, message, Divider, Switch,
} from "antd";
import {
  UserOutlined, DeleteOutlined, PlayCircleOutlined, StopOutlined,
  ReloadOutlined, InfoCircleOutlined,
} from "@ant-design/icons";
```

Thêm Card sau Card "Lưu cURL Moderator" (trước đóng `</>` của block moderator), chỉ hiện khi `modStatus?.configured`:

```tsx
              {/* Automation Settings Card */}
              {modStatus?.configured && (
                <Card title="Cài đặt tự động" style={{ marginBottom: 16 }}>
                  <Space direction="vertical" style={{ width: "100%" }}>
                    <Space>
                      <Switch
                        checked={nickSettings?.ai_reply_enabled ?? false}
                        onChange={(v) => handleToggleSetting("ai_reply_enabled", v)}
                        loading={settingsLoading}
                        disabled={!isScanning}
                      />
                      <span>Bật AI Reply</span>
                      {!isScanning && (
                        <Tag icon={<InfoCircleOutlined />} color="warning">
                          Cần đang quét
                        </Tag>
                      )}
                    </Space>
                    <Space>
                      <Switch
                        checked={nickSettings?.auto_reply_enabled ?? false}
                        onChange={(v) => handleToggleSetting("auto_reply_enabled", v)}
                        loading={settingsLoading}
                        disabled={!isScanning}
                      />
                      <span>Bật Auto-reply (tự động reply comment mới)</span>
                    </Space>
                    <Space>
                      <Switch
                        checked={nickSettings?.auto_post_enabled ?? false}
                        onChange={(v) => handleToggleSetting("auto_post_enabled", v)}
                        loading={settingsLoading}
                        disabled={!isScanning}
                      />
                      <span>Bật Auto-post (đăng comment theo lịch)</span>
                    </Space>

                    {nickSettings?.auto_reply_enabled && (
                      <Tag color={nickSettings.ai_reply_enabled ? "purple" : "blue"}>
                        {nickSettings.ai_reply_enabled
                          ? "Đang reply bằng AI"
                          : "Đang reply bằng template ngẫu nhiên"}
                      </Tag>
                    )}
                    {nickSettings?.auto_post_enabled && (
                      <Tag color="green">Đang đăng comment theo lịch</Tag>
                    )}
                  </Space>
                </Card>
              )}
```

- [ ] **Step 4: Build kiểm tra không có TypeScript error**

```bash
cd frontend
npm run build
```

Expected: `✓ built in ...` không có error.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/LiveScan.tsx frontend/src/api/nickLive.ts
git commit -m "feat: add automation toggles card to LiveScan page"
```

---

## Tổng kết kiểm tra cuối

- [ ] Backend tests pass: `cd backend && python -m pytest tests/ -v`
- [ ] Server khởi động không lỗi: `uvicorn app.main:app`
- [ ] Frontend build không lỗi: `cd frontend && npm run build`
- [ ] Trang `/settings` load được, lưu OpenAI config thành công
- [ ] Trang Live Scan: chọn nick → thấy card Cài đặt tự động sau khi cấu hình moderator
- [ ] Toggle auto-reply/auto-post phản hồi đúng (disable khi chưa scanning)
