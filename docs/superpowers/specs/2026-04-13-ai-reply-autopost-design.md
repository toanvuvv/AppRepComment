# Design: AI Reply, Auto-reply & Auto-post cho Shopee Live

**Date:** 2026-04-13  
**Status:** Approved  

---

## Tổng quan

Mở rộng app quét comment Shopee Live với 3 tính năng mới:
1. **AI Reply** — tự động reply comment khách bằng OpenAI (contextual)
2. **Auto-reply** — tự động reply bằng template ngẫu nhiên (non-AI)
3. **Auto-post** — tự động đăng comment theo lịch xoay vòng

Cấu hình được chia làm 2 cấp:
- **Global/Shared** — OpenAI config, system prompt, reply templates, auto-post templates
- **Per-nick** — toggle bật/tắt từng tính năng cho từng NickLive

---

## Database Schema

### Bảng mới (SQLite)

```sql
-- Cài đặt toàn app (key-value)
CREATE TABLE app_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
-- Keys: openai_api_key, openai_model, ai_system_prompt

-- Template reply cho khách (shared, non-AI mode)
CREATE TABLE reply_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Template auto-post theo lịch (shared)
CREATE TABLE auto_post_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    min_interval_seconds INTEGER NOT NULL DEFAULT 60,
    max_interval_seconds INTEGER NOT NULL DEFAULT 300,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Cài đặt per-nick
CREATE TABLE nick_live_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nick_live_id INTEGER UNIQUE NOT NULL REFERENCES nick_lives(id) ON DELETE CASCADE,
    ai_reply_enabled BOOLEAN NOT NULL DEFAULT 0,
    auto_reply_enabled BOOLEAN NOT NULL DEFAULT 0,
    auto_post_enabled BOOLEAN NOT NULL DEFAULT 0
);
```

### Chiến lược memory cache

Khi server khởi động, load toàn bộ `app_settings` và templates vào memory. Runtime dùng cache, không query DB liên tục. Cache invalidated khi user cập nhật qua API.

---

## Backend

### Services mới / mở rộng

#### `settings_service.py` (mới)
- `get_setting(key)` / `set_setting(key, value)` — thao tác với `app_settings`
- `get_openai_config()` → `{ api_key, model }`
- `get_system_prompt()` → `str`
- `get_reply_templates()` → `list[ReplyTemplate]`
- `get_auto_post_templates()` → `list[AutoPostTemplate]`
- CRUD cho `reply_templates` và `auto_post_templates`
- `load_cache()` — gọi khi startup, đọc DB vào memory

#### `ai_reply_service.py` (mới)
- `generate_reply(system_prompt, comment_text, guest_name) → str`
- Gọi OpenAI Chat Completions API
- System prompt = cấu hình từ app_settings
- User message = comment của khách
- Trả về text để ghép vào `@guest_name {text}`

#### `live_moderator.py` (mở rộng)
- `start_auto_reply_loop(nick_live_id)` — lắng nghe comment queue mới
  - Nếu `ai_reply_enabled`: gọi `ai_reply_service` → `send_reply()`
  - Nếu không: random pick từ `reply_templates` → `send_reply()`
- `stop_auto_reply_loop(nick_live_id)`
- `start_auto_post_loop(nick_live_id)` — mỗi template chạy 1 asyncio task:
  - `sleep(random(min_interval, max_interval))`
  - Post content (không @mention, dùng cấu trúc message thông thường)
  - Lặp lại
- `stop_auto_post_loop(nick_live_id)` — cancel tất cả tasks của nick đó

### API Routes mới

#### `/api/settings` (router mới)

| Method | Path | Mô tả |
|--------|------|--------|
| GET | `/api/settings/openai` | Lấy OpenAI config (key masked) |
| PUT | `/api/settings/openai` | Cập nhật API key + model |
| GET | `/api/settings/system-prompt` | Lấy system prompt |
| PUT | `/api/settings/system-prompt` | Cập nhật system prompt |
| GET | `/api/settings/reply-templates` | Danh sách reply templates |
| POST | `/api/settings/reply-templates` | Thêm template |
| DELETE | `/api/settings/reply-templates/{id}` | Xoá template |
| GET | `/api/settings/auto-post-templates` | Danh sách auto-post templates |
| POST | `/api/settings/auto-post-templates` | Thêm template |
| PUT | `/api/settings/auto-post-templates/{id}` | Cập nhật template |
| DELETE | `/api/settings/auto-post-templates/{id}` | Xoá template |

#### `/api/nick-lives/{id}/settings` (mở rộng router hiện có)

| Method | Path | Mô tả |
|--------|------|--------|
| GET | `/api/nick-lives/{id}/settings` | Lấy per-nick settings |
| PUT | `/api/nick-lives/{id}/settings` | Cập nhật toggles |

Khi PUT:
- `auto_reply_enabled = true` → `moderator.start_auto_reply_loop(id)`
- `auto_reply_enabled = false` → `moderator.stop_auto_reply_loop(id)`
- `auto_post_enabled = true` → `moderator.start_auto_post_loop(id)`
- `auto_post_enabled = false` → `moderator.stop_auto_post_loop(id)`

**Điều kiện bật loop:** Moderator phải đã cấu hình + scanner đang chạy.

---

## Frontend

### Trang Settings mới

Thêm route `/settings` vào sidebar/menu.

**Card 1: Cấu hình OpenAI**
- Input: API Key (type=password, masked)
- Select: Model (`gpt-4o`, `gpt-4o-mini`, `gpt-3.5-turbo`)
- Button: Lưu

**Card 2: System Prompt**
- TextArea: nội dung prompt cha (dùng cho AI reply)
- Button: Lưu

**Card 3: Reply Templates** (shared)
- Danh sách các template, mỗi cái 1 dòng
- Button Thêm / nút Xoá từng cái
- Ghi chú: "Dùng trong non-AI mode, chọn ngẫu nhiên khi reply"

**Card 4: Auto-post Templates** (shared)
- Mỗi template: `[content textarea] [min giây] ~ [max giây] [Xoá]`
- Button: Thêm mới
- Ghi chú: "Hệ thống post xoay vòng theo interval ngẫu nhiên trong khoảng min~max"

### Thay đổi trang LiveScan

Thêm **Card: Cài đặt tự động** khi đã chọn nick + moderator đã cấu hình:

```
[ Toggle ] Bật AI Reply
[ Toggle ] Bật Auto-reply (tự động reply comment mới)
[ Toggle ] Bật Auto-post (đăng comment theo lịch)

Status indicator:
- Auto-reply ON + AI ON  → "Đang reply bằng AI"
- Auto-reply ON + AI OFF → "Đang reply bằng template ngẫu nhiên"
- Auto-post ON           → "Đang đăng comment theo lịch"
```

Disable toggles khi: moderator chưa cấu hình hoặc scanner chưa chạy.

---

## Luồng hoạt động

### Auto-reply (AI mode)
```
Comment mới → scanner queue
  → auto_reply_loop nhận comment (dùng queue riêng, không ảnh hưởng UI queue)
  → gọi ai_reply_service.generate_reply(system_prompt, comment_text, guest_name)
  → OpenAI API trả về reply_text
  → moderator.send_reply(nick_live_id, session_id, guest_name, guest_id, reply_text)
  → POST https://live.shopee.vn/api/v1/session/{session_id}/message
     body: { content: "@guest_name {reply_text}", ... }
```

> **Queue isolation:** Scanner broadcast comment đến nhiều consumer (UI queue + auto-reply queue). Dùng pattern pub/sub: scanner giữ list các subscriber queue, khi có comment mới thì put vào tất cả.

### Auto-reply (non-AI mode)
```
Comment mới → scanner queue
  → auto_reply_loop nhận comment
  → random.choice(reply_templates)
  → moderator.send_reply(..., reply_text=template.content)
```

### Auto-post
```
Khi bật auto_post_enabled:
  session_id lấy từ scanner.get_status(nick_live_id)["session_id"]
  Với mỗi template trong auto_post_templates:
    asyncio task:
      loop:
        wait random(min_interval, max_interval) giây
        POST message với content = template.content (không @mention, không place_holders)
        URL: https://live.shopee.vn/api/v1/session/{session_id}/message
```

> **Session ID:** Auto-post loop lấy session_id từ scanner tại thời điểm post (không cache), để đảm bảo đúng session đang live.

---

## Phụ thuộc mới

- `openai` Python package (OpenAI SDK)

---

## Những gì KHÔNG thay đổi

- Cơ chế parse cURL moderator
- Cấu trúc message body gửi lên Shopee
- Scanner (comment_scanner.py)
- NickLive model và CRUD hiện có
