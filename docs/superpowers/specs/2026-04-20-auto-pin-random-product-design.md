# Auto Pin Random Product — Design Spec

**Date:** 2026-04-20
**Status:** Approved design, ready for implementation plan
**Owner:** toanvuvv

## 1. Mục tiêu

Với mỗi `nick_live` đã parse sản phẩm (có `KnowledgeProduct` records), cho phép user bật một vòng lặp tự động **pin sản phẩm ngẫu nhiên** vào livestream định kỳ — gọi API `POST https://api.relive.vn/livestream/show` với `item_id` + `shop_id` của sản phẩm được chọn.

Feature độc lập với Auto Post (auto-comment) hiện có và bật/tắt riêng per nick.

## 2. Quyết định thiết kế

| Vấn đề | Quyết định |
|---|---|
| Interval | Min/Max random, đơn vị **phút**, user tự nhập (1–60) |
| Nguồn sản phẩm | Chỉ `KnowledgeProduct` có `in_stock=True` của nick |
| Anti-repeat | **Không** — random thuần túy, trùng liên tiếp cũng chấp nhận |
| Kênh gửi | Chỉ **host cookies** (`NickLive.cookies`) |
| Start/Stop | Toggle độc lập + nút thủ công trong `NickConfigModal` |
| Không có sản phẩm in_stock | Skip lần đó, loop tiếp (không dừng) |
| Lịch sử pin | **Không ghi** — không lưu DB, không log reply_logs |

## 3. Data Model

### Mở rộng `nick_live_settings`

Thêm 3 cột vào `NickLiveSetting` (`app/models/settings.py`):

```python
auto_pin_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
pin_min_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
pin_max_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
```

**Validation (schema layer):** `1 <= min <= max <= 60`.

**Migration**: `alembic/versions/<rev>_add_auto_pin_columns.py` — 3 `op.add_column` với `server_default` để tương thích rows cũ.

Không tạo bảng mới (không có khái niệm "pin templates").

## 4. Service Layer

### 4.1 `relive_service.py` — thêm hàm

```python
_RELIVE_SHOW_URL = "https://api.relive.vn/livestream/show"

async def pin_livestream_item(
    api_key: str,
    cookies: str,
    session_id: int,
    item_id: int,
    shop_id: int,
    proxy: str | None = None,
) -> dict[str, Any]:
    payload = {
        "apikey": api_key,
        "cookie": cookies,
        "session_id": session_id,
        "item": json.dumps({"item_id": item_id, "shop_id": shop_id}),
        "country": "vn",
        "proxy": proxy or "",
    }
    # POST, raise ValueError on non-200 / invalid JSON, return parsed dict
```

### 4.2 `auto_pinner.py` — service mới

Mirror pattern của `AutoPoster` (`app/services/auto_poster.py`):

```python
class AutoPinner:
    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}

    def is_running(self, nick_live_id: int) -> bool: ...
    async def start(self, nick_live_id: int, session_id: int, cookies: str) -> dict: ...
    async def stop(self, nick_live_id: int) -> dict: ...
    def stop_all(self) -> None: ...
    def stop_user_nicks(self, user_id: int) -> None: ...

    async def _loop(self, nick_live_id: int, session_id: int, cookies: str) -> None:
        while True:
            # load settings fresh mỗi vòng (user có thể đổi interval)
            settings = load NickLiveSetting(nick_live_id)
            interval = random.uniform(
                settings.pin_min_interval_minutes * 60,
                settings.pin_max_interval_minutes * 60,
            )
            await asyncio.sleep(interval)

            products = [p for p in KP.get_products(nick_live_id) if p.in_stock]
            if not products:
                logger.warning(f"Auto-pin nick={nick_live_id}: no in_stock products, retry next cycle")
                continue

            pick = random.choice(products)
            api_key = SettingsService(db, user_id).get_setting("relive_api_key")
            proxy = NickLiveSetting.host_proxy
            try:
                await pin_livestream_item(
                    api_key, cookies, session_id,
                    pick.item_id, pick.shop_id, proxy,
                )
                logger.info(f"Auto-pin nick={nick_live_id} item={pick.item_id} shop={pick.shop_id}")
            except Exception:
                logger.exception(f"Auto-pin failed nick={nick_live_id}")
                # swallow, loop tiếp
```

### 4.3 Start guards (trả error tiếng Việt)

| Điều kiện | Error |
|---|---|
| `auto_pin_enabled=False` | `"Auto Pin chưa được bật"` |
| Không có `relive_api_key` | `"Chưa cấu hình Relive API key"` |
| Không có sản phẩm `in_stock=True` | `"Chưa có sản phẩm còn hàng để pin"` |
| Đã chạy | `{"status": "already_running"}` |

### 4.4 Singleton & lifecycle

- Instance singleton khởi tạo trong `app/main.py` lifespan.
- Shutdown: gọi `auto_pinner.stop_all()`.
- Admin lock user → `auto_pinner.stop_user_nicks(user_id)` (song song với `auto_poster.stop_user_nicks`).
- Xóa `NickLive` → stop loop pin của nick đó trong xử lý delete.

## 5. API Layer

### 5.1 Endpoints mới

```
POST /api/nick-lives/{nick_live_id}/auto-pin/start
  body: { session_id: int }
  → 200 {status: "started" | "already_running"}
  → 400 {detail: "<tiếng Việt>"}
  → 404 nếu không sở hữu nick

POST /api/nick-lives/{nick_live_id}/auto-pin/stop
  → 200 {status: "stopped" | "not_running"}

GET  /api/nick-lives/{nick_live_id}/auto-pin/status
  → 200 {running: bool}
```

Ownership: reuse `_require_nick_ownership` helper.

### 5.2 Settings update schema

`app/schemas/settings.py` — extend `NickLiveSettingUpdate`:

```python
auto_pin_enabled: bool | None = None
pin_min_interval_minutes: int | None = Field(None, ge=1, le=60)
pin_max_interval_minutes: int | None = Field(None, ge=1, le=60)

@model_validator(mode="after")
def _check_pin_interval(self):
    if self.pin_min_interval_minutes is not None and self.pin_max_interval_minutes is not None:
        if self.pin_min_interval_minutes > self.pin_max_interval_minutes:
            raise ValueError("Pin min interval phải <= max interval")
    return self
```

## 6. Frontend

### 6.1 `NickConfigModal.tsx` — thêm section "Auto Pin sản phẩm"

Đặt dưới section Auto Post hiện có.

```
┌─ Auto Pin sản phẩm ──────────────────────┐
│ [✓] Bật tự động pin sản phẩm             │
│                                          │
│ Pin ngẫu nhiên mỗi:                      │
│   Min: [ 2 ] phút    Max: [ 5 ] phút    │
│                                          │
│ Trạng thái: ● Đang chạy / ○ Đã dừng      │
│ [ Bắt đầu Pin ]  [ Dừng Pin ]            │
└──────────────────────────────────────────┘
```

### 6.2 Behavior

- Toggle + 2 input → PATCH settings (giống các toggle khác trong modal).
- "Bắt đầu Pin" → POST `/auto-pin/start` với `session_id` hiện tại (lấy từ context giống auto-post).
- "Dừng Pin" → POST `/auto-pin/stop`.
- Polling GET `/auto-pin/status` mỗi 5s khi modal mở (reuse pattern status auto-post nếu có).
- Validate client-side: `1 <= min <= max <= 60`, error inline.
- Disable "Bắt đầu Pin" khi `auto_pin_enabled=false` hoặc chưa có sản phẩm in_stock nào.

### 6.3 API client

Thêm `startAutoPin`, `stopAutoPin`, `getAutoPinStatus` cạnh các hàm auto-post hiện có.

## 7. Error Handling & Edge Cases

**Loop level** (`_loop`):

| Tình huống | Xử lý |
|---|---|
| Không có sản phẩm in_stock | `logger.warning`, `continue` |
| Relive API fail (network/HTTP/JSON) | `logger.exception`, swallow, `continue` |
| DB load fail | `logger.exception`, `continue` |
| `asyncio.CancelledError` | log info, cleanup, exit |
| Exception khác | log exception, cleanup task trong `finally` |

**Không ghi vào `reply_logs`** — giữ ngữ nghĩa bảng đó cho reply/auto-post.

## 8. Testing

### 8.1 Unit tests

- `tests/test_auto_pinner.py`:
  - `test_start_requires_enabled`
  - `test_start_requires_api_key`
  - `test_start_requires_in_stock_products`
  - `test_start_idempotent` (2 lần start → lần 2 `already_running`)
  - `test_stop_cancels_task`
  - `test_loop_skips_when_no_in_stock`
  - `test_loop_swallows_relive_error`
  - `test_loop_picks_only_in_stock`
  - `test_stop_user_nicks`

- `tests/test_relive_service.py` (extend):
  - `test_pin_livestream_item_payload_shape` — `item` là JSON string, đúng keys
  - `test_pin_livestream_item_http_error` → `ValueError`

- `tests/test_auto_pin_router.py`:
  - Start/stop có/không ownership (404 nếu không sở hữu)
  - PATCH settings `min > max` → 422
  - PATCH `min=0` hoặc `max=61` → 422

### 8.2 Frontend

Smoke test manual: toggle + nút start/stop gọi đúng endpoint, interval validation inline.

### 8.3 Coverage

80%+ cho `auto_pinner.py` và `relive_service.pin_livestream_item`.

## 9. Files thay đổi

**New:**
- `backend/app/services/auto_pinner.py`
- `backend/alembic/versions/<rev>_add_auto_pin_columns.py`
- `backend/tests/test_auto_pinner.py`
- `backend/tests/test_auto_pin_router.py`

**Modified:**
- `backend/app/models/settings.py` (3 cột mới)
- `backend/app/schemas/settings.py` (fields + validator)
- `backend/app/services/relive_service.py` (thêm `pin_livestream_item`)
- `backend/app/routers/nick_live.py` hoặc file router mới `auto_pin.py` (3 endpoints)
- `backend/app/main.py` (singleton + lifespan hooks)
- `backend/app/routers/admin.py` (lock user → stop_user_nicks pin)
- `backend/tests/test_relive_service.py` (extend)
- `frontend/src/components/NickConfigModal.tsx` (section mới + API calls)
- `frontend/src/api/` hoặc nơi đang có auto-post client (hàm mới)

## 10. Out of scope (YAGNI)

- Track lịch sử pin vào DB
- Anti-repeat / round-robin
- Pin qua moderator channel
- Cho user chọn subset sản phẩm được phép pin
- Dashboard analytics số lần pin
