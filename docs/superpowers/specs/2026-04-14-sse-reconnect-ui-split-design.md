# SSE Reconnect + UI Model Split Design

**Date:** 2026-04-14
**Status:** Approved
**Approach:** Approach 1 — SSE Reconnect + State Split

## Problem

1. **F5 kills scanning UI**: Backend `CommentScanner` keeps running asyncio tasks, but frontend loses all state on refresh — `isScanning` resets to `false`, polling stops, comments disappear.
2. **UI jank from comments**: `LiveScan.tsx` (862 lines) holds all state in one component. New comments trigger `setComments()` which re-renders the entire page (nick list, sessions, moderator, products).
3. **No state isolation**: Products, comments, and scanning state all live in the same component tree with no memoization boundaries.

## Solution Overview

Three changes:
1. Replace frontend polling with **SSE (Server-Sent Events)** + auto-reconnect after F5
2. Extract **product info** into isolated UI model (hook + memo)
3. Extract **comment feed** into isolated UI model (component + SSE hook + memo)

---

## Section 1: Backend State Persistence + Frontend Auto-Reconnect

### Current Flow
- Frontend starts scan → backend creates asyncio task
- Frontend polls every 3s via `setInterval` + `getScanStatus()` + `getComments()`
- F5 → all React state resets → polling never starts again

### New Flow
- On nick selection, frontend calls `getScanStatus(nickId)`
- If `is_scanning === true` → auto-set `isScanning=true` + connect SSE
- Replace `setInterval` polling with `EventSource` to `/api/nick-lives/{id}/comments/stream`
- SSE pushes new comments in real-time (backend endpoint already exists)
- On SSE disconnect → auto-reconnect with exponential backoff (1s, 2s, 4s, max 10s)
- On reconnect → call `getComments()` once to load existing comments, then SSE for new ones

### Files Changed
- `frontend/src/hooks/useSSEComments.ts` — NEW: SSE connection management
- `frontend/src/pages/LiveScan.tsx` — MODIFY: remove polling `useEffect`, use SSE hook

### Hook API
```typescript
interface UseSSECommentsOptions {
  nickLiveId: number | null;
  isScanning: boolean;
  onComment?: (comment: CommentItem) => void;
}

interface UseSSECommentsReturn {
  comments: CommentItem[];
  commentCount: number;
  isConnected: boolean;
}

function useSSEComments(options: UseSSECommentsOptions): UseSSECommentsReturn;
```

### Reconnect Behavior
- `EventSource` `onerror` → close current connection
- Wait `delay` ms (1s initial, double each retry, cap at 10s)
- Create new `EventSource`
- On successful reconnect → fetch full comments list once via REST

---

## Section 2: Product Info — Separate UI Model

### Current State
- `KnowledgeProductsCard` is already a separate component (good)
- But it renders in the same tree as `LiveScan.tsx` — scanning state changes cause product card re-renders

### Changes
- Create `useKnowledgeProducts(nickLiveId)` custom hook
  - Manages: `products`, `loading`, `importProducts()`, `deleteProducts()`
  - Encapsulates all API calls to `/api/nick-lives/{id}/knowledge/products`
- Wrap `KnowledgeProductsCard` with `React.memo()`
  - Only re-renders when `nickLiveId` changes
  - Product state completely isolated from scanning/comment state

### Files Changed
- `frontend/src/hooks/useKnowledgeProducts.ts` — NEW: product CRUD state
- `frontend/src/components/KnowledgeProductsCard.tsx` — MODIFY: use hook, add React.memo

---

## Section 3: Comment Feed — Separate UI Model

### Current State
- Comment list renders inline in `LiveScan.tsx` (lines 575-645)
- Every new comment → `setComments()` → entire `LiveScan` re-renders

### Changes
- Create `CommentFeed` component
  - Receives: `nickLiveId`, `isScanning`
  - Internally uses `useSSEComments` hook for SSE connection
  - Manages its own `comments` state
  - Auto-scroll logic stays inside this component
  - Wrapped with `React.memo()` — only re-renders on `nickLiveId` or `isScanning` change
- Expose comments to parent via `onCommentsChange` callback
  - Moderator reply section needs access to comments list
  - Parent stores a ref/state of comments for reply, but does NOT trigger re-render of CommentFeed

### Files Changed
- `frontend/src/components/CommentFeed.tsx` — NEW: SSE-powered comment list
- `frontend/src/pages/LiveScan.tsx` — MODIFY: replace inline comment rendering

---

## New File Structure

```
frontend/src/
├── components/
│   ├── CommentFeed.tsx              # NEW: SSE + comment list + auto-scroll
│   ├── KnowledgeProductsCard.tsx    # MODIFY: React.memo + use hook
│   └── Layout.tsx                   # unchanged
├── hooks/
│   ├── useSSEComments.ts            # NEW: SSE connection + reconnect
│   └── useKnowledgeProducts.ts      # NEW: product CRUD state
├── pages/
│   └── LiveScan.tsx                 # MODIFY: ~500 lines, orchestrator only
```

## LiveScan.tsx After Refactor

`LiveScan.tsx` becomes an orchestrator:
- Nick selection + CRUD
- Session management
- Scan start/stop (calls backend, sets `isScanning`)
- On mount/nick change → check `getScanStatus()` for auto-reconnect
- Renders `<CommentFeed>` and `<KnowledgeProductsCard>` as isolated children
- Moderator section stays in LiveScan (it's tightly coupled to nick + scan state)

Estimated: 862 lines → ~500 lines.

## Re-render Isolation

| Event | What re-renders | What does NOT re-render |
|-------|----------------|------------------------|
| New comment arrives (SSE) | `CommentFeed` only | Nick list, sessions, moderator, products |
| Product imported/deleted | `KnowledgeProductsCard` only | Comments, sessions, moderator |
| Scan started/stopped | `LiveScan` + children (expected) | N/A (state change is intentional) |
| Nick selected | Everything (expected) | N/A |

## Auto-Reconnect on F5

```
User hits F5
  → LiveScan mounts
  → selectedId restored? No (React state resets)
  → User re-selects nick
  → useEffect calls getScanStatus(nickId)
  → Backend returns { is_scanning: true, comment_count: 150 }
  → setIsScanning(true)
  → CommentFeed mounts → useSSEComments connects SSE
  → Loads 150 existing comments via REST
  → SSE streams new comments from that point
  → UI fully restored without re-starting scan
```

## Out of Scope

- Persisting `selectedId` across F5 (could add later with localStorage)
- WebSocket (SSE is sufficient for server→client push)
- State management library (React hooks + memo is enough)
- Backend changes (SSE endpoint + scanner already work correctly)
