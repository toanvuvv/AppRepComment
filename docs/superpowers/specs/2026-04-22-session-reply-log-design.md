# Session-based Reply Log + Clear + 3-day Retention

**Date:** 2026-04-22
**Status:** Approved design

## Problem

Hiện tại `ReplyLog` đã lưu `session_id` + `nick_live_id`, nhưng:

1. API `/api/reply-logs` không cho filter theo `session_id` → user không tách được log theo từng phiên live.
2. Không có API xóa log → user không thể clear log theo ý mình.
3. Model comment ghi "retained ~24h" nhưng không có background job thực thi retention.

User muốn: xem log reply comment theo từng **phiên live riêng biệt** cho từng nick, có nút **Clear session đang xem**, và log **tự động xóa sau 3 ngày**.

## Goals

- User mở modal log của 1 nick → thấy dropdown chọn session → load đúng log của session đó.
- Nút "🗑 Clear session này" xóa đúng log session đang xem, có confirm.
- Log cũ hơn 3 ngày tự động xóa bằng background job.

## Non-goals

- Không thay đổi schema `ReplyLog` (đã có `session_id`).
- Không export/archive log trước khi xóa.
- Không cho user chọn retention tùy chỉnh (fixed 3 ngày).
- Không giữ "Clear all" per nick (chỉ clear 1 session đang xem).

## Design

### 1. Backend API changes (`backend/app/routers/reply_logs.py`)

**Endpoint mới: `GET /api/reply-logs/sessions`**

Query param: `nick_live_id: int` (required).

Response:
```json
[
  {"session_id": 12345, "first_at": "2026-04-22T08:00:00Z", "last_at": "2026-04-22T10:30:00Z", "count": 342},
  ...
]
```

SQL (group by session, newest last-activity first):
```sql
SELECT session_id, MIN(created_at) AS first_at, MAX(created_at) AS last_at, COUNT(*) AS count
FROM reply_logs
WHERE nick_live_id = :nid
GROUP BY session_id
ORDER BY MAX(created_at) DESC
```

Ownership: verify `nick_live_id` thuộc `current_user` qua `_owned_nick_ids` (pattern sẵn có).

**Endpoint sửa: `GET /api/reply-logs`**

Thêm param optional `session_id: int | None`. Nếu có → thêm filter `ReplyLog.session_id == session_id`. Các filter khác giữ nguyên.

**Endpoint mới: `DELETE /api/reply-logs`**

Query params (required): `nick_live_id: int`, `session_id: int`.

Logic:
```python
owned = _owned_nick_ids(current_user.id, db)
deleted = (
    db.query(ReplyLog)
    .filter(ReplyLog.nick_live_id == nick_live_id)
    .filter(ReplyLog.nick_live_id.in_(owned))   # ownership guard
    .filter(ReplyLog.session_id == session_id)
    .delete(synchronize_session=False)
)
db.commit()
return {"deleted": deleted}
```

Response: `{"deleted": <int>}`. Nếu nick không thuộc user → `deleted=0` (không 403 để tránh enumerate; hoặc trả 404 — chọn 404 cho rõ ý định).

Quyết định: trả `404` khi `nick_live_id` không thuộc user — consistent với semantics "không tìm thấy tài nguyên của bạn".

### 2. Retention → 3 ngày (sửa config, không tạo service mới)

Codebase đã có `_reply_log_cleanup_loop` trong `backend/app/main.py` chạy mỗi `REPLY_LOG_CLEANUP_INTERVAL_SEC` (1h), xóa row `created_at < now - REPLY_LOG_RETENTION_HOURS`.

**Thay đổi duy nhất:** trong `backend/app/config.py`, đổi `REPLY_LOG_RETENTION_HOURS: int = 24` → `72`.

**Update comment trong `backend/app/models/reply_log.py`:** đổi "Retained ~24h" → "Retained 3 days (72h) via main._reply_log_cleanup_loop".

Không thêm file service mới.

### 3. Frontend API client (`frontend/src/api/replyLogs.ts`)

Thêm:

```typescript
export interface ReplyLogSession {
  session_id: number;
  first_at: string;
  last_at: string;
  count: number;
}

export interface ListReplyLogsParams {
  nick_live_id?: number;
  session_id?: number;   // NEW
  outcome?: ReplyOutcome;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
}

export async function listReplyLogSessions(
  nickLiveId: number
): Promise<ReplyLogSession[]> {
  const res = await apiClient.get("/reply-logs/sessions", {
    params: { nick_live_id: nickLiveId },
  });
  return res.data;
}

export async function deleteReplyLogSession(
  nickLiveId: number,
  sessionId: number
): Promise<{ deleted: number }> {
  const res = await apiClient.delete("/reply-logs", {
    params: { nick_live_id: nickLiveId, session_id: sessionId },
  });
  return res.data;
}
```

### 4. Frontend hook (`frontend/src/hooks/useReplyLogs.ts`)

Mở rộng signature:

```typescript
export function useReplyLogs(
  nickLiveId: number | null,
  enabled: boolean,
  sessionId: number | null = null   // NEW — null = current/all
): UseReplyLogsResult
```

- `fetchOnce` truyền `session_id: sessionId ?? undefined` vào `listReplyLogs`.
- Poll mỗi 2.5s như cũ — chỉ đổi filter.
- Stats endpoint vẫn gọi cho toàn nick (không lọc session) — giữ hiện tại.

Thêm hook mới `useReplyLogSessions`:

```typescript
export function useReplyLogSessions(
  nickLiveId: number | null,
  enabled: boolean
): { sessions: ReplyLogSession[]; refresh: () => void }
```

Poll cùng interval (2.5s) khi modal mở — đơn giản. Session "active" (đang ghi log) sẽ luôn đứng đầu do sort theo `MAX(created_at) DESC`.

### 5. Frontend UI (`frontend/src/pages/LiveScan.tsx`)

Trong Reply Logs modal (line ~636-648 hiện tại):

```tsx
<Modal title="Tất cả Reply Logs" ...>
  <Space style={{ marginBottom: 12 }}>
    <Select
      style={{ width: 320 }}
      value={selectedSessionId}
      onChange={setSelectedSessionId}
      options={sessions.map(s => ({
        value: s.session_id,
        label: `Session #${s.session_id} · ${fmtTime(s.first_at)}–${fmtTime(s.last_at)} · ${s.count} reply`,
      }))}
    />
    <Popconfirm
      title="Xóa toàn bộ log của session này?"
      onConfirm={handleClearSession}
    >
      <Button danger icon={<DeleteOutlined />}>Clear session này</Button>
    </Popconfirm>
  </Space>
  {/* existing log list, but filtered to selectedSessionId */}
</Modal>
```

- State mới: `selectedSessionId: number | null` trong `LiveScan.tsx`.
- Default: khi mở modal, pick `sessions[0].session_id` (session mới nhất) nếu có.
- `handleClearSession`: gọi `deleteReplyLogSession` → refetch sessions + logs. Nếu session hiện tại biến mất → auto-select session mới nhất còn lại hoặc `null`.
- `useReplyLogs(selectedId, isScanning, selectedSessionId)` khi modal mở; khi modal đóng vẫn dùng `sessionId=null` để summary card bên ngoài hiện log hiện tại của nick.

Quyết định: **summary card (line 580-) tiếp tục hiện log mới nhất toàn nick** (không filter session) — giữ UX hiện tại. Chỉ modal mới có filter session.

### 6. Tests

**Backend** (`backend/tests/`):

- `test_reply_logs_sessions.py`:
  - `test_list_sessions_groups_by_session_id` — tạo logs với 2 session, assert response có đúng 2 entry, sort by last_at desc.
  - `test_list_sessions_ownership` — user khác không thấy session của nick mình.
  - `test_list_logs_filters_by_session_id` — thêm param `session_id`, chỉ trả logs đúng session.
- `test_reply_logs_delete.py`:
  - `test_delete_session_removes_only_that_session` — 2 sessions, delete 1, session kia còn.
  - `test_delete_session_ownership_returns_404` — user khác → 404, không xóa.
  - `test_delete_session_returns_count` — response `{"deleted": N}`.
- `test_reply_log_janitor.py`:
  - `test_janitor_purges_old_rows` — inject log với `created_at = now - 4 days`, gọi `_purge_sync()`, row bị xóa.
  - `test_janitor_keeps_recent_rows` — log trong 3 ngày không bị xóa.
  - `test_janitor_start_stop_idempotent` — start 2 lần, stop sạch.

**Frontend:** smoke test thủ công (modal mở → dropdown hiện sessions → chọn → logs filter đúng → clear button xóa + refresh). Không thêm unit test FE (project không có khung test FE hiện hữu — check lại trong plan).

### 7. Gitnexus impact check

Trước khi sửa code (trong plan execution):

- `gitnexus_impact({target: "list_reply_logs", direction: "upstream"})` — kiểm tra caller của endpoint.
- `gitnexus_impact({target: "useReplyLogs", direction: "upstream"})` — FE caller.
- `gitnexus_impact({target: "reply_log_writer", direction: "upstream"})` — đảm bảo không break lifespan startup order.

Nếu HIGH/CRITICAL → warn user, hold lại.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Janitor xóa dồn 1 lần nhiều row → lock bảng | `DELETE` có index `created_at` → fast; chunk nếu cần (để plan sau nếu thấy vấn đề). 3 ngày retention trên nick 20 pax là vài chục ngàn rows max. |
| User clear session đang live → mất log debug | Confirm dialog; chỉ xóa khi user chủ động. |
| Poll session list mỗi 2.5s tốn query | Query `GROUP BY session_id` trên index `(nick_live_id, created_at)` — rẻ. Chấp nhận. |
| Race: janitor chạy lúc writer đang flush | DB-level; SQLAlchemy session riêng biệt, commit độc lập. Không có shared state Python. |

## Rollout

1. Backend first (API + janitor + tests) — độc lập, deploy được trước.
2. Frontend (API client + hook + UI) — build sau khi BE xanh.
3. Không cần migration DB.

## Acceptance criteria

- [ ] `GET /api/reply-logs/sessions?nick_live_id=X` trả danh sách session đúng, sort by last_at desc, có count.
- [ ] `GET /api/reply-logs?session_id=Y` chỉ trả logs của session Y.
- [ ] `DELETE /api/reply-logs?nick_live_id=X&session_id=Y` xóa đúng session, respect ownership (404 cho nick không sở hữu).
- [ ] Janitor chạy mỗi giờ, xóa log > 3 ngày. Start/stop sạch trong lifespan.
- [ ] Modal Reply Logs có dropdown session + nút Clear (có confirm).
- [ ] Clear thành công → refetch sessions + logs → UI update.
- [ ] Tests pass (backend).
