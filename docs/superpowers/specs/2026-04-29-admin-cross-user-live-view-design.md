# Admin Cross-User Live View — Design

**Date:** 2026-04-29
**Status:** Draft (awaiting user review)

## 1. Problem

Hiện tại trang `LiveScan` và các endpoint `/api/nick-lives/*` đều khoá theo `current_user.id`. Admin bị chặn khỏi nick live của user khác, không thể xem hoặc thao tác hộ. Yêu cầu: admin truy cập đầy đủ live của mọi user.

## 2. Goals

- Admin xem được live (nick list, sessions, comments, logs, status) của bất kỳ user nào.
- Admin thao tác (start/stop scan, edit cookies, gửi reply, đổi settings, auto-post, auto-pin, host config, CRUD templates) với **full parity** trên live của user khác.
- Hành vi với non-admin user **không đổi**.

## 3. Non-goals

- Không thêm audit table / cột audit. Hành động admin được ghi **trong suốt** (như chính chủ user thao tác).
- Không thay đổi quota, mô hình permission, hoặc thêm role mới.
- Không refactor router khác ngoài nhóm liên quan đến trang LiveScan.

## 4. UX

### Admin
- Trang `LiveScan`, header thêm dropdown: **"Đang xem live của: <username> ▼"**.
  - Default: chính admin.
  - Chọn user khác → toàn bộ data trong trang reload theo user đó.
  - Khi đang xem hộ: hiển thị banner cảnh báo `"Bạn đang xem live của <username> với quyền admin"` + nút `"← về live của tôi"`.
- Dropdown lấy danh sách user từ `GET /api/admin/users` (đã có).

### Non-admin
- Không thấy dropdown / banner. Hành vi y hệt hiện tại.

## 5. Backend Architecture

### 5.1 Param convention

Mọi endpoint thuộc nhóm "LiveScan" nhận query param tuỳ chọn `as_user_id: int | None`:

```
GET  /api/nick-lives?as_user_id=42
POST /api/nick-lives/123/scan/start?session_id=...&as_user_id=42
GET  /api/nick-lives/123/comments/stream?token=...&as_user_id=42
... (áp dụng cho TẤT CẢ endpoint trong nhóm)
```

### 5.2 Helper mới — `app/dependencies.py`

```python
def resolve_user_context(
    as_user_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if as_user_id is None or as_user_id == user.id:
        return user
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    target = db.get(User, as_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target user not found")
    return target
```

### 5.3 Quy tắc

- `as_user_id is None` hoặc `== caller.id` → trả caller (hành vi cũ).
- Non-admin truyền `as_user_id` khác id mình → `403 Admin only`.
- Admin truyền `as_user_id` không tồn tại → `404 Target user not found`.
- Admin truyền hợp lệ → trả `User` của target. Mọi ownership filter dùng `ctx_user.id`.

### 5.4 Endpoint sweep

Các router cần thay `Depends(get_current_user)` bằng `Depends(resolve_user_context)` và đổi `current_user.id` → `ctx_user.id`:

- `app/routers/nick_live.py` — toàn bộ file (mọi endpoint).
- Các router phụ trợ phục vụ trang LiveScan, sửa cùng pattern (xác nhận chính xác trong implementation plan):
  - `app/routers/knowledge.py` (per-nick knowledge — dùng cho reply AI)
  - `app/routers/host_config.py` (nếu tồn tại tách rời)
  - `app/routers/reply_logs.py`
  - `app/routers/settings.py` (chỉ phần per-user / per-nick, không phải system keys)

Router **không** sửa: `admin.py`, `auth.py`, `seeding.py` (ngoài scope), system-keys endpoints.

### 5.5 Background services

`auto_poster`, `auto_pinner`, `scanner`, `moderator`, `live_moderator` đều key theo `nick_live_id` và đọc owner `user_id` từ DB. Action của admin tự động ghi log dưới danh nghĩa owner thật → đáp ứng yêu cầu "transparent". **Không sửa.**

### 5.6 Database

Không migration. Không thêm cột mới.

## 6. Frontend Architecture

### 6.1 State

Mở rộng zustand store:

```ts
interface ViewAsState {
  viewAsUserId: number | null  // null = chính mình
  setViewAsUserId: (id: number | null) => void
}
```

### 6.2 API client

Trong `frontend/src/api/client.ts` (hoặc helper chung): nếu `viewAsUserId != null` và `currentUser.role === "admin"` → tự gắn `as_user_id=<id>` vào query string của mọi request thuộc namespace `/api/nick-lives/*` (và các route khác đã chuyển sang `resolve_user_context`).

SSE URL builder (`comments/stream`) phải append cùng `token`.

### 6.3 `pages/LiveScan.tsx`

- Render dropdown chỉ khi `currentUser.role === "admin"`.
- `onChange(userId)` → `setViewAsUserId(userId)` → invalidate React Query keys của trang (nick list, sessions, scan stats, comments) → reload.
- Banner + nút reset khi `viewAsUserId !== null`.

### 6.4 Endpoint danh sách user cho dropdown

Dùng `GET /api/admin/users` (đã có, đã trả `nick_count`). Hiển thị `username (n nicks)` để admin chọn.

## 7. Testing

### 7.1 Backend (pytest)

File mới `backend/tests/test_nick_live_admin_view.py`:

- `test_admin_can_list_target_user_nicks` — admin gọi `GET /api/nick-lives?as_user_id=B` → trả nick của B, status 200.
- `test_non_admin_forbidden_with_as_user_id` — user thường gọi `?as_user_id=<other>` → 403.
- `test_admin_target_not_found` — `as_user_id=99999` → 404.
- `test_admin_no_param_sees_own_nicks` — admin không truyền param → vẫn chỉ thấy nick của chính admin (regression).
- `test_admin_start_scan_for_other_user` — admin start scan trên nick của B → scanner chạy, log ghi nick.user_id = B.
- `test_admin_send_reply_for_other_user` — admin gửi reply qua moderator endpoint với `as_user_id=B` → reply gửi thành công, `reply_log.nick_live_id` thuộc B.
- `test_admin_sse_stream_for_other_user` — connect SSE với `as_user_id=B&token=<admin_token>` → nhận comment của nick B.
- `test_admin_update_settings_for_other_user` — `PUT /api/nick-lives/{id}/settings?as_user_id=B` → settings của B đổi.

### 7.2 Regression

Chạy lại `test_nick_live*`, `test_admin*`, `test_auto_pin_router*`, `test_admin_router*` — phải pass nguyên trạng.

### 7.3 Frontend

Smoke test thủ công:
1. Admin login → trang LiveScan → thấy dropdown.
2. Chọn user B → bảng nick load nick của B → banner hiện.
3. Bật scan trên 1 nick của B → status đổi → comments stream chảy.
4. Gửi reply qua moderator → reply xuất hiện trong live B.
5. Bấm "về live của tôi" → trở lại nick của admin.
6. Login non-admin → không thấy dropdown / banner.

## 8. Edge Cases & Risks

| # | Rủi ro | Xử lý |
|---|--------|-------|
| 1 | Caller bị lock | `get_current_user` đã chặn caller bị lock. Caller admin lock chính mình không thể xảy ra (admin route đã chặn `Cannot lock yourself`). |
| 2 | Target user bị lock | Vẫn cho admin xem/thao tác (lock áp cho caller, không cho target). Hành vi đúng — admin có thể debug user bị lock. |
| 3 | FE quên append `as_user_id` ở 1 endpoint | Hiển thị data của admin thay vì target. Mitigate: gắn tại interceptor chung + grep test review. |
| 4 | Cookies plaintext của user khác lộ cho admin | Chấp nhận theo full-parity. Không thay đổi. |
| 5 | Quota khi admin tạo nick hộ user | Tính vào `target.max_nicks` (đã đúng vì code dùng `ctx_user.max_nicks`). |
| 6 | Race khi admin và chính chủ user cùng start scan 1 nick | Scanner đã chặn `Already scanning` (existing). Không thay đổi. |
| 7 | Admin xem live của admin khác | Cho phép (cả 2 đều role admin). Không có quy tắc cấm. |

## 9. Rollout

1. Backend: thêm helper + sweep endpoint + tests → deploy.
2. Frontend: thêm store flag + interceptor + dropdown → deploy.
3. Không feature flag — backward compatible (param optional).

## 10. Out of scope (tham khảo cho tương lai)

- Audit log riêng cho admin actions.
- Phân quyền hạt mịn (vd "admin chỉ xem, không edit").
- Trang dashboard tổng hợp tất cả nick live của tất cả user trong 1 bảng (đã loại ở Câu 1, phương án C).
