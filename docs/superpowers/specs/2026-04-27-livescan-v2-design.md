# LiveScan v2 — Table-First UI with Background Multi-Scan

**Date:** 2026-04-27
**Page:** `/live-scan`
**Status:** Approved (design phase)
**Author:** brainstorming session

---

## 1. Problem

Trang `/live-scan` hiện tại có 3 vấn đề về UX:

1. **Card grid tốn diện tích** — danh sách nick dạng card 4 cột, không nhìn được nhiều nick cùng lúc, không thấy trạng thái live ở cấp tổng quan.
2. **Phải bấm thủ công "Kiểm tra phiên live"** cho từng nick → flow chậm, dễ bỏ sót nick đang live.
3. **Mỗi lần chỉ scan 1 nick** (state `selectedId` đơn lẻ). Backend đã hỗ trợ scan song song nhưng UI ép single-select.

Người dùng muốn: bảng có auto-detect session + toggle scan độc lập từng row + có thể scan nhiều nick song song.

---

## 2. Goals & Non-Goals

### Goals
- Hiển thị toàn bộ nick + trạng thái live trong 1 bảng dày đặc thông tin.
- Auto-detect sessionId định kỳ (60s) cho mọi nick — không cần click thủ công.
- Toggle scan độc lập per-row, hỗ trợ scan song song nhiều nick.
- Đóng modal feed **không** ảnh hưởng scan đang chạy ngầm.
- Tránh rate-limit Shopee bằng batch endpoint + throttling.

### Non-Goals
- Không thay đổi backend scan engine (`startScan`/`stopScan` API giữ nguyên).
- Không thay đổi schema reply logs.
- Không thay đổi cơ chế cookies/auth.
- Không làm dashboard tổng (nhiều nick) — chỉ table + focus modal.

---

## 3. Architectural Foundation — Global Store

Đây là quyết định nền tảng. Hiện tại SSE và comments state nằm trong component (`useSSEComments`, `useState`) → khi component unmount (đóng modal/đổi nick), kết nối SSE đứt và comments mất. Với multi-scan, cần state tập trung.

### `frontend/src/stores/liveScanStore.ts` (Zustand)

```typescript
interface LiveScanStore {
  // Sessions cache (keyed by nickLiveId)
  sessionsByNick: Map<number, { active: LiveSession | null; lastFetched: number }>;

  // Scan state
  scanningNickIds: Set<number>;

  // Comments buffer per-nick (max 500 each, ring buffer)
  commentsByNick: Map<number, CommentItem[]>;

  // SSE connection registry
  sseConnections: Map<number, EventSource>;

  // Mini-stats per scanning nick (5min window)
  miniStatsByNick: Map<number, { commentsNew: number; repliesOk: number; repliesFail: number }>;

  // Actions
  startScanFor(nickId: number, sessionId: number): Promise<void>;
  stopScanFor(nickId: number): Promise<void>;
  upsertSession(nickId: number, session: LiveSession | null): void;
  appendComment(nickId: number, comment: CommentItem): void;
  setMiniStats(nickId: number, stats: MiniStats): void;
  clearComments(nickId: number): void;
}
```

### Lifecycle rules
- `startScanFor`: gọi backend `startScan`, sau đó **mở SSE** và đăng ký vào `sseConnections`. Comments mới đẩy vào `commentsByNick` qua `appendComment`.
- `stopScanFor`: gọi `stopScan`, **đóng SSE**, giữ comments trong buffer (user có thể scroll back) cho đến khi `clearComments` được gọi.
- SSE độc lập với UI mounting. Đóng modal = không chạm SSE.
- Buffer giới hạn 500 comments/nick (FIFO drop) để tránh memory leak.

---

## 4. UI Layout

### Page structure

```
┌────────────────────────────────────────────────────────────┐
│  Quét Comment Live Shopee  [+ Thêm nick] [↻ Refresh all]  │
├────────────────────────────────────────────────────────────┤
│  NickLiveTable                                              │
│   ┌──┬─────────┬─────────┬──────┬───────┬────────┬──────┬───┐
│   │  │ Nick    │ Live    │ Sess │ Views │ C/R 5' │ Scan │ ⋯ │
│   ├──┼─────────┼─────────┼──────┼───────┼────────┼──────┼───┤
│   │🟢│ @abc    │ 🔴 live │ 1234 │ 89    │ +12/✓8 │ [ON] │ ⋯ │
│   │  │ @xyz    │ ⚪ off  │ —    │ —     │ —      │ ─OFF │ ⋯ │
│   │  │ @uuu    │ ⚠️ cookie│ ?    │ ?     │ —      │ ─OFF │ ⋯ │
│   └──┴─────────┴─────────┴──────┴───────┴────────┴──────┴───┘
└────────────────────────────────────────────────────────────┘

Modals (open on demand):
- AddNickModal — paste JSON
- CookieEditModal — current edit-cookies modal extracted
- FocusFeedModal — Comments + Reply Logs tabs
- NickConfigModal — existing, unchanged
```

### Click behavior
- Click row (any cell except Scan/Action) → open `FocusFeedModal` for that nick.
- Click Scan switch → toggle scan, **không** mở modal.
- Click action icons → respective modal/popconfirm.

---

## 5. Component Specs

### 5.1 `NickLiveTable.tsx`

| Cột | Render | Width |
|---|---|---|
| Nick | Avatar + name + user_id (Text secondary nhỏ dưới name) | 240 |
| Trạng thái | Badge: `🔴 Đang live` / `⚪ Offline` / `⚠️ Cookie hết hạn` (Tag color đỏ + CTA inline) | 160 |
| Session | `#{sessionId}` + Tooltip(title). Trống nếu offline. | 100 |
| Viewers | Number, format compact (`1.2k`) | 90 |
| C/R 5' | `+{commentsNew} / ✓{repliesOk}` + tooltip breakdown. Trống nếu không scan. | 110 |
| Scan | `<Switch>`. Disabled khi offline hoặc cookie expired. Loading khi đang start/stop. | 80 |
| Action | Icon-only group: ⚙ Config, 🍪 Cookies, 🗑 Xóa (Popconfirm) | 120 |

Row visual states:
- Đang scan → background `#f6ffed`, viền trái `4px solid #52c41a`.
- Cookie expired → background `#fffbe6`, hiện CTA "Cập nhật cookies" thay cho status.
- Hover → cursor pointer trừ ô Scan/Action.

### 5.2 `ScanToggleSwitch.tsx`

Props: `nickId: number`. Đọc store: `scanningNickIds.has(nickId)`, `sessionsByNick.get(nickId)?.active`.

```
- isLive = !!session?.active && session.active.status === 1
- isScanning = scanningNickIds.has(nickId)
- disabled = !isLive || cookieExpired
- onChange(checked):
    if (checked && session?.sessionId) startScanFor(nickId, sessionId)
    else stopScanFor(nickId)
```

Hiển thị Spin khi đang gọi API. Toast lỗi khi backend trả 4xx/5xx.

### 5.3 `FocusFeedModal.tsx`

Props: `nickId: number | null`, `onClose()`.

```
<Modal width={1000} bodyStyle={{ height: '80vh' }}>
  <Title>@{nick.name} — Session #{sessionId}</Title>
  <Tabs>
    <TabPane key="comments" tab="Comments">
      <CommentFeedView nickId={nickId} />  {/* reads from store */}
    </TabPane>
    <TabPane key="logs" tab="Reply Logs">
      <ReplyLogsPanel nickId={nickId} />   {/* extracted from current code */}
    </TabPane>
  </Tabs>
</Modal>
```

Closing modal: chỉ unmount UI, **không** call `stopScanFor`. SSE tiếp tục, store vẫn nhận comments.

Switch nick: nếu modal đang mở cho nick A, click row B → đổi `nickId` prop, không close-reopen → smooth.

### 5.4 `CommentFeedView.tsx` (refactored)

Khác `CommentFeed.tsx` cũ ở chỗ:
- **Không** tự gọi `useSSEComments` nữa.
- Đọc `commentsByNick.get(nickId)` từ store.
- Logic auto-scroll, replyLogIndex tagging giữ nguyên.
- `useSSEComments` được di chuyển vào store action `startScanFor`.

### 5.5 `AddNickModal.tsx` & `CookieEditModal.tsx`

Extract từ inline code hiện tại của `LiveScan.tsx`. Logic API call không đổi.

### 5.6 Hooks mới

```typescript
// Polls batch sessions for ALL nicks every 60s
function useNickLiveSessionsPoll(nickIds: number[]): void;
// Fires GET /api/nick-lives/sessions?ids=1,2,3 → updates store

// Polls mini-stats for SCANNING nicks every 15s
function useScanStatsPoll(scanningNickIds: number[]): void;
// Fires GET /api/nick-lives/{id}/scan-stats?window=300 per nick (parallel, max 5 at a time)
```

---

## 6. Backend Changes

### 6.1 New endpoint: batch sessions

```
GET /api/nick-lives/sessions?ids=1,2,3
→ {
    "sessions": {
      "1": { "active_session": {...} | null, "all_sessions": [...] },
      "2": { "active_session": null, "all_sessions": [] },
      "3": { "active_session": {...}, "all_sessions": [...] }
    }
  }
```

**Implementation:** Loop qua `ids`, gọi Shopee API tuần tự với `asyncio.sleep(0.2)` giữa các call để throttle. Errors per-nick không fail toàn batch — trả error trong response body.

**File:** `backend/app/routers/nick_live.py` — thêm endpoint `list_sessions_batch`.

### 6.2 New endpoint: scan stats

```
GET /api/nick-lives/{id}/scan-stats?window=300
→ {
    "comments_new": 12,    // comments received in last 300s
    "replies_ok": 8,
    "replies_fail": 2,
    "replies_dropped": 1,
    "window_seconds": 300
  }
```

**Implementation:**
- `comments_new`: thêm in-memory counter vào scan engine (per nick, increment khi push SSE event). Endpoint trả về `counter - counterAt(now - window)` — duy trì 1 deque `(timestamp, total)` cho mỗi nick scanning.
- `replies_*`: SQL count trên `reply_logs` filter `nick_live_id = ? AND created_at > now - window`.

**Cookie-expired signal:** Khi scan engine bắt 401/403 từ Shopee, emit SSE event `{type: "cookie_expired"}` trước khi đóng stream. Frontend store lắng nghe event này và update flag `cookieExpiredByNick`.

**File:** `backend/app/routers/nick_live.py` + `backend/app/services/reply_log_service.py`.

### 6.3 No changes to
- `startScan` / `stopScan` / `getScanStatus` — giữ nguyên.
- SSE endpoint — giữ nguyên.
- DB schema — không migration.

---

## 7. State Transitions & Edge Cases

| Trường hợp | Hành vi |
|---|---|
| User bật toggle nhưng nick chưa có session active | Backend reject 4xx, store rollback toggle, toast "Nick này không đang live" |
| Đang scan, session kết thúc (status → 0) | Auto-detect 60s phát hiện → tự gọi `stopScanFor`, toast "Phiên live đã kết thúc" |
| Cookie hết hạn giữa lúc scan | Backend SSE phát error event → store mark `cookieExpired`, đóng SSE, hiện CTA |
| User xóa nick đang scan | Confirm → `stopScanFor` rồi mới `deleteNickLive`. Nếu modal đang focus nick này → close modal. |
| User mở modal cho nick offline | Modal hiện "Nick này chưa live, không có comments". Tab Reply Logs vẫn xem được logs cũ. |
| Page refresh trong lúc đang scan | `useEffect` mount → `getScanStatus` cho từng nick → restore `scanningNickIds`. Comments buffer mất (chấp nhận, comments mới sẽ tới qua SSE). |
| 20 nick + 5 đang scan | Mỗi 60s: 1 batch call (20 ids). Mỗi 15s: 5 stat calls. SSE: 5 connection. OK. |

---

## 8. File Structure

### New files
```
frontend/src/
├── stores/liveScanStore.ts
├── components/livescan/
│   ├── NickLiveTable.tsx
│   ├── ScanToggleSwitch.tsx
│   ├── FocusFeedModal.tsx
│   ├── CommentFeedView.tsx          (refactored from CommentFeed.tsx)
│   ├── ReplyLogsPanel.tsx           (extracted from LiveScan.tsx)
│   ├── AddNickModal.tsx
│   └── CookieEditModal.tsx
└── hooks/
    ├── useNickLiveSessionsPoll.ts
    └── useScanStatsPoll.ts
```

### Modified files
```
frontend/src/pages/LiveScan.tsx           — rewrite as table-first composition
frontend/src/api/nickLive.ts              — add listSessionsBatch, getScanStats
frontend/src/components/CommentFeed.tsx   — DEPRECATED (replaced by CommentFeedView)
backend/app/routers/nick_live.py          — add 2 endpoints
backend/app/services/reply_log_service.py — add scan_stats query method
backend/tests/test_nick_live_router.py    — tests for new endpoints
```

---

## 9. Build Order

1. **Backend batch sessions endpoint** + tests
2. **Backend scan-stats endpoint** + tests
3. **Frontend store** (`liveScanStore.ts`) + unit tests for store actions
4. **Refactor `CommentFeed` → `CommentFeedView`** reading from store; verify SSE moved into store
5. **`NickLiveTable` + `ScanToggleSwitch`** with placeholder modal
6. **`useNickLiveSessionsPoll` + `useScanStatsPoll`** + wire to table
7. **`FocusFeedModal` Comments tab**
8. **`FocusFeedModal` Reply Logs tab** (port from current modal logic)
9. **`AddNickModal` + `CookieEditModal`** extraction
10. **Rewrite `LiveScan.tsx`** composing all pieces; remove old cards
11. **Smoke test full flow**: add nick → auto-detect → toggle scan → focus modal → close → reopen → stop → delete

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Batch session call bị Shopee rate-limit khi nhiều nick | Throttle 200ms giữa các call trong loop; cache 60s; nếu fail cá biệt nick → giữ data cũ + tag stale |
| Memory leak nếu nick scan nhiều giờ | Buffer 500 comments/nick (FIFO); SSE tự reconnect đã có sẵn |
| Race: user toggle nhanh ON/OFF | Optimistic UI + queue last action; nếu API conflict → rollback theo response |
| Modal mở trong lúc nick đổi session | Modal title cập nhật theo `sessionsByNick.get(nickId).active.sessionId` reactively |
| Test E2E khó vì SSE | Mock `EventSource` trong store tests; component tests dùng store stub |

---

## 11. Migration / Rollback

- Không có DB migration → rollback chỉ cần revert frontend + 2 endpoints backend (vẫn tương thích cũ).
- Có thể giữ route `/live-scan-old` tạm thời nếu user muốn so sánh, nhưng không khuyến nghị (duplicate code).

---

## 12. Open Questions

(không có — design đã được duyệt qua brainstorm)
