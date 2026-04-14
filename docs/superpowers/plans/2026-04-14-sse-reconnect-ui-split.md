# SSE Reconnect + UI Model Split — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace frontend polling with SSE, auto-reconnect after F5, and split comments + products into isolated UI models to eliminate UI jank.

**Architecture:** Frontend switches from 3s `setInterval` polling to `EventSource` SSE (backend endpoint already exists). Two custom hooks (`useSSEComments`, `useKnowledgeProducts`) encapsulate state. Two `React.memo`-wrapped components (`CommentFeed`, `KnowledgeProductsCard`) isolate re-renders.

**Tech Stack:** React 18, TypeScript, EventSource (native browser API), Ant Design, FastAPI SSE (existing)

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| CREATE | `frontend/src/hooks/useSSEComments.ts` | SSE connection, reconnect, comment state |
| CREATE | `frontend/src/hooks/useKnowledgeProducts.ts` | Product CRUD state |
| CREATE | `frontend/src/components/CommentFeed.tsx` | Comment list UI with auto-scroll |
| MODIFY | `frontend/src/components/KnowledgeProductsCard.tsx` | Use hook, add React.memo |
| MODIFY | `frontend/src/pages/LiveScan.tsx` | Remove polling + inline comments, use new components |

No backend changes needed — SSE endpoint at `GET /api/nick-lives/{id}/comments/stream` already works.

---

### Task 1: Create `useSSEComments` hook

**Files:**
- Create: `frontend/src/hooks/useSSEComments.ts`

- [ ] **Step 1: Create the hook file**

```typescript
// frontend/src/hooks/useSSEComments.ts
import { useEffect, useRef, useState, useCallback } from "react";
import { type CommentItem, getComments, getScanStatus } from "../api/nickLive";

interface UseSSECommentsOptions {
  nickLiveId: number | null;
  isScanning: boolean;
}

interface UseSSECommentsReturn {
  comments: CommentItem[];
  commentCount: number;
  isConnected: boolean;
}

const API_KEY = import.meta.env.VITE_APP_API_KEY ?? "";

function buildSSEUrl(nickLiveId: number): string {
  const base = `/api/nick-lives/${nickLiveId}/comments/stream`;
  return API_KEY ? `${base}?api_key=${API_KEY}` : base;
}

export function useSSEComments({
  nickLiveId,
  isScanning,
}: UseSSECommentsOptions): UseSSECommentsReturn {
  const [comments, setComments] = useState<CommentItem[]>([]);
  const [commentCount, setCommentCount] = useState(0);
  const [isConnected, setIsConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const retryDelayRef = useRef(1000);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cleanup = useCallback(() => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    setIsConnected(false);
  }, []);

  useEffect(() => {
    if (!nickLiveId || !isScanning) {
      cleanup();
      if (!isScanning) {
        setComments([]);
        setCommentCount(0);
      }
      return;
    }

    let cancelled = false;

    async function connectSSE() {
      if (cancelled || !nickLiveId) return;

      // Load existing comments first
      try {
        const existing = await getComments(nickLiveId);
        if (!cancelled) {
          setComments(existing);
          setCommentCount(existing.length);
        }
      } catch {
        // Will retry via SSE reconnect
      }

      if (cancelled) return;

      const es = new EventSource(buildSSEUrl(nickLiveId));
      esRef.current = es;

      es.addEventListener("comment", (event) => {
        try {
          const comment: CommentItem = JSON.parse(event.data);
          setComments((prev) => [...prev, comment]);
          setCommentCount((prev) => prev + 1);
        } catch {
          // Ignore parse errors
        }
      });

      es.addEventListener("ping", () => {
        // Keep-alive, no action needed
      });

      es.onopen = () => {
        setIsConnected(true);
        retryDelayRef.current = 1000; // Reset backoff on success
      };

      es.onerror = () => {
        es.close();
        esRef.current = null;
        setIsConnected(false);

        if (!cancelled) {
          const delay = retryDelayRef.current;
          retryDelayRef.current = Math.min(delay * 2, 10000);
          retryTimerRef.current = setTimeout(connectSSE, delay);
        }
      };
    }

    connectSSE();

    return () => {
      cancelled = true;
      cleanup();
    };
  }, [nickLiveId, isScanning, cleanup]);

  return { comments, commentCount, isConnected };
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors related to `useSSEComments.ts`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useSSEComments.ts
git commit -m "feat: add useSSEComments hook with SSE connection and auto-reconnect"
```

---

### Task 2: Create `useKnowledgeProducts` hook

**Files:**
- Create: `frontend/src/hooks/useKnowledgeProducts.ts`

- [ ] **Step 1: Create the hook file**

```typescript
// frontend/src/hooks/useKnowledgeProducts.ts
import { useCallback, useEffect, useState } from "react";
import { message } from "antd";
import {
  type KnowledgeProduct,
  getKnowledgeProducts,
  importKnowledgeProducts,
  deleteKnowledgeProducts,
} from "../api/knowledge";

interface UseKnowledgeProductsReturn {
  products: KnowledgeProduct[];
  loading: boolean;
  importLoading: boolean;
  loadProducts: () => Promise<void>;
  handleImport: (rawJson: string) => Promise<boolean>;
  handleDeleteAll: () => Promise<void>;
}

export function useKnowledgeProducts(
  nickLiveId: number | null
): UseKnowledgeProductsReturn {
  const [products, setProducts] = useState<KnowledgeProduct[]>([]);
  const [loading, setLoading] = useState(false);
  const [importLoading, setImportLoading] = useState(false);

  const loadProducts = useCallback(async () => {
    if (!nickLiveId) return;
    setLoading(true);
    try {
      const data = await getKnowledgeProducts(nickLiveId);
      setProducts(data);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [nickLiveId]);

  useEffect(() => {
    loadProducts();
  }, [loadProducts]);

  const handleImport = useCallback(
    async (rawJson: string): Promise<boolean> => {
      if (!nickLiveId || !rawJson.trim()) {
        message.warning("Paste JSON data truoc");
        return false;
      }
      setImportLoading(true);
      try {
        const data = await importKnowledgeProducts(nickLiveId, rawJson);
        setProducts(data);
        message.success(`Import thanh cong ${data.length} san pham`);
        return true;
      } catch (err: unknown) {
        const errorMsg =
          err instanceof Error ? err.message : "Import that bai";
        message.error(errorMsg);
        return false;
      } finally {
        setImportLoading(false);
      }
    },
    [nickLiveId]
  );

  const handleDeleteAll = useCallback(async () => {
    if (!nickLiveId) return;
    try {
      await deleteKnowledgeProducts(nickLiveId);
      setProducts([]);
      message.success("Da xoa tat ca san pham");
    } catch {
      message.error("Xoa that bai");
    }
  }, [nickLiveId]);

  return {
    products,
    loading,
    importLoading,
    loadProducts,
    handleImport,
    handleDeleteAll,
  };
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors related to `useKnowledgeProducts.ts`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useKnowledgeProducts.ts
git commit -m "feat: add useKnowledgeProducts hook for isolated product state"
```

---

### Task 3: Create `CommentFeed` component

**Files:**
- Create: `frontend/src/components/CommentFeed.tsx`

- [ ] **Step 1: Create the component file**

```tsx
// frontend/src/components/CommentFeed.tsx
import { memo, useEffect, useRef } from "react";
import { Badge, Button, Card, Space, Spin, Typography } from "antd";
import { StopOutlined } from "@ant-design/icons";
import { type CommentItem } from "../api/nickLive";
import { useSSEComments } from "../hooks/useSSEComments";

const { Text } = Typography;

function formatTs(ts?: number): string {
  if (!ts) return "";
  const ms = ts > 1e12 ? ts : ts * 1000;
  return new Date(ms).toLocaleTimeString("vi-VN");
}

function getDisplayName(c: CommentItem): string {
  return c.userName || c.username || c.nick_name || c.nickname || "Unknown";
}

function getCommentText(c: CommentItem): string {
  return c.content || c.comment || c.message || c.msg || "";
}

interface CommentFeedProps {
  nickLiveId: number | null;
  isScanning: boolean;
  onStopScan: () => void;
  onCommentsChange?: (comments: CommentItem[]) => void;
}

function CommentFeedInner({
  nickLiveId,
  isScanning,
  onStopScan,
  onCommentsChange,
}: CommentFeedProps) {
  const { comments, commentCount, isConnected } = useSSEComments({
    nickLiveId,
    isScanning,
  });

  const commentsEndRef = useRef<HTMLDivElement>(null);
  const commentContainerRef = useRef<HTMLDivElement>(null);
  const userScrolledUpRef = useRef(false);
  const prevCommentCountRef = useRef(0);

  // Notify parent of comments changes
  useEffect(() => {
    onCommentsChange?.(comments);
  }, [comments, onCommentsChange]);

  // Auto-scroll on new comments
  useEffect(() => {
    if (
      comments.length > prevCommentCountRef.current &&
      !userScrolledUpRef.current
    ) {
      commentsEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
    prevCommentCountRef.current = comments.length;
  }, [comments.length]);

  if (!isScanning || !nickLiveId) return null;

  return (
    <Card
      title={
        <Space>
          <Spin size="small" />
          <span>Dang quet...</span>
          <Badge
            count={commentCount}
            overflowCount={99999}
            style={{ backgroundColor: "#52c41a" }}
          />
          {!isConnected && (
            <Text type="warning" style={{ fontSize: 12 }}>
              (dang ket noi lai...)
            </Text>
          )}
        </Space>
      }
      extra={
        <Button
          type="primary"
          danger
          icon={<StopOutlined />}
          onClick={onStopScan}
        >
          Dung quet
        </Button>
      }
    >
      <div
        ref={commentContainerRef}
        onScroll={() => {
          const el = commentContainerRef.current;
          if (!el) return;
          userScrolledUpRef.current =
            el.scrollHeight - el.scrollTop - el.clientHeight > 100;
        }}
        style={{
          maxHeight: 500,
          overflowY: "auto",
          padding: "8px 0",
          contain: "layout style",
        }}
      >
        {comments.length === 0 ? (
          <Text type="secondary">Chua co comment nao...</Text>
        ) : (
          comments.map((c, idx) => (
            <div
              key={c.id || idx}
              style={{
                padding: "6px 12px",
                borderBottom: "1px solid #f0f0f0",
                display: "flex",
                gap: 8,
                alignItems: "flex-start",
              }}
            >
              <Text
                type="secondary"
                style={{ fontSize: 12, flexShrink: 0 }}
              >
                {formatTs(c.timestamp || c.create_time || c.ctime)}
              </Text>
              <Text strong style={{ flexShrink: 0, color: "#1677ff" }}>
                {getDisplayName(c)}:
              </Text>
              <Text>{getCommentText(c)}</Text>
            </div>
          ))
        )}
        <div ref={commentsEndRef} />
      </div>
    </Card>
  );
}

const CommentFeed = memo(CommentFeedInner);
export default CommentFeed;
export type { CommentFeedProps };
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors related to `CommentFeed.tsx`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/CommentFeed.tsx
git commit -m "feat: add CommentFeed component with SSE and isolated re-renders"
```

---

### Task 4: Refactor `KnowledgeProductsCard` to use hook + React.memo

**Files:**
- Modify: `frontend/src/components/KnowledgeProductsCard.tsx`

- [ ] **Step 1: Refactor the component to use the hook and wrap with memo**

Replace the entire file content. Key changes:
- Remove internal state management (`useState` for products, loading, importLoading)
- Remove `loadProducts`, `handleImport`, `handleDeleteAll` functions
- Import and use `useKnowledgeProducts` hook
- Wrap export with `memo()`

```tsx
// frontend/src/components/KnowledgeProductsCard.tsx
import { memo, useState } from "react";
import {
  Button,
  Card,
  Input,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import {
  DeleteOutlined,
  ImportOutlined,
  DatabaseOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { type KnowledgeProduct } from "../api/knowledge";
import { useKnowledgeProducts } from "../hooks/useKnowledgeProducts";

const { TextArea } = Input;
const { Text } = Typography;

interface Props {
  nickLiveId: number | null;
}

function KnowledgeProductsCardInner({ nickLiveId }: Props) {
  const { products, loading, importLoading, handleImport, handleDeleteAll } =
    useKnowledgeProducts(nickLiveId);
  const [rawJson, setRawJson] = useState("");

  const onImport = async () => {
    const success = await handleImport(rawJson);
    if (success) setRawJson("");
  };

  const parseKeywords = (raw: string): string[] => {
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  };

  const parseJson = (raw: string | null): string[] => {
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  };

  const formatPrice = (val: number | null): string => {
    if (val === null) return "-";
    return `${val.toLocaleString("vi-VN")}d`;
  };

  const columns: ColumnsType<KnowledgeProduct> = [
    {
      title: "#",
      dataIndex: "product_order",
      width: 50,
      sorter: (a, b) => a.product_order - b.product_order,
    },
    {
      title: "Ten san pham",
      dataIndex: "name",
      ellipsis: true,
      width: 250,
    },
    {
      title: "Keywords",
      dataIndex: "keywords",
      width: 200,
      render: (val: string) =>
        parseKeywords(val).map((kw, i) => (
          <Tag key={i} color="blue" style={{ marginBottom: 2 }}>
            {kw}
          </Tag>
        )),
    },
    {
      title: "Gia",
      width: 150,
      render: (_: unknown, r: KnowledgeProduct) => {
        const price =
          r.price_min === r.price_max
            ? formatPrice(r.price_min)
            : `${formatPrice(r.price_min)} - ${formatPrice(r.price_max)}`;
        return (
          <span>
            {price}
            {r.discount_pct ? (
              <Tag color="red" style={{ marginLeft: 4 }}>
                -{r.discount_pct}%
              </Tag>
            ) : null}
          </span>
        );
      },
    },
    {
      title: "Khuyen mai",
      width: 120,
      render: (_: unknown, r: KnowledgeProduct) => {
        const vouchers = parseJson(r.voucher_info);
        if (!vouchers.length) return "-";
        return vouchers.map((v: string, i: number) => (
          <Tag key={i} color="orange" style={{ marginBottom: 2 }}>
            {v}
          </Tag>
        ));
      },
    },
    {
      title: "Ton kho",
      dataIndex: "stock_qty",
      width: 80,
      render: (val: number | null, r: KnowledgeProduct) => (
        <Tag color={r.in_stock ? "green" : "red"}>
          {r.in_stock ? val ?? "Co" : "Het"}
        </Tag>
      ),
    },
    {
      title: "Da ban",
      dataIndex: "sold",
      width: 80,
      render: (val: number | null) => (val ? `${val}+` : "-"),
    },
    {
      title: "Rating",
      dataIndex: "rating",
      width: 80,
      render: (val: number | null, r: KnowledgeProduct) =>
        val ? `${val}/5 (${r.rating_count ?? 0})` : "-",
    },
  ];

  if (!nickLiveId) return null;

  return (
    <Card
      title={
        <Space>
          <DatabaseOutlined />
          <span>Knowledge Products</span>
          <Tag color="blue">{products.length} san pham</Tag>
        </Space>
      }
      style={{ marginBottom: 16 }}
      extra={
        products.length > 0 ? (
          <Popconfirm
            title="Xoa tat ca san pham?"
            onConfirm={handleDeleteAll}
            okText="Xoa"
            cancelText="Huy"
          >
            <Button danger icon={<DeleteOutlined />} size="small">
              Xoa tat ca
            </Button>
          </Popconfirm>
        ) : null
      }
    >
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <div>
          <Text type="secondary">
            Paste JSON response tu Shopee (data gio hang live) de import san
            pham:
          </Text>
          <TextArea
            rows={4}
            placeholder='{"err_code": 0, "data": {"items": [...]}}'
            value={rawJson}
            onChange={(e) => setRawJson(e.target.value)}
            style={{ marginTop: 8 }}
          />
          <Button
            type="primary"
            icon={<ImportOutlined />}
            onClick={onImport}
            loading={importLoading}
            disabled={!rawJson.trim()}
            style={{ marginTop: 8 }}
          >
            Import san pham
          </Button>
        </div>

        {products.length > 0 && (
          <Table
            dataSource={products}
            columns={columns}
            rowKey="pk"
            size="small"
            pagination={false}
            loading={loading}
            scroll={{ x: 800 }}
          />
        )}
      </Space>
    </Card>
  );
}

const KnowledgeProductsCard = memo(KnowledgeProductsCardInner);
export default KnowledgeProductsCard;
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/KnowledgeProductsCard.tsx
git commit -m "refactor: KnowledgeProductsCard uses hook + React.memo for isolation"
```

---

### Task 5: Refactor `LiveScan.tsx` — remove polling, use new components

**Files:**
- Modify: `frontend/src/pages/LiveScan.tsx`

This is the largest change. Key modifications:
1. Remove polling `useEffect` (lines 131-153)
2. Remove `comments`, `commentCount` state — now owned by `CommentFeed`
3. Remove inline comment rendering (lines 575-645)
4. Add auto-reconnect: check `getScanStatus` on nick selection
5. Use `<CommentFeed>` and pass `onCommentsChange` callback
6. Keep a `commentsRef` for moderator reply (does NOT trigger re-renders)

- [ ] **Step 1: Rewrite LiveScan.tsx**

Replace the entire file. The full replacement:

```tsx
// frontend/src/pages/LiveScan.tsx
import { useState, useEffect, useRef, useCallback } from "react";
import {
  Card,
  Button,
  Input,
  Avatar,
  Row,
  Col,
  Table,
  Alert,
  Badge,
  Tag,
  Space,
  Typography,
  Popconfirm,
  message,
  Divider,
  Switch,
} from "antd";
import {
  UserOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import {
  type NickLive,
  type LiveSession,
  type CommentItem,
  type ModeratorStatus,
  type ModeratorReplyResult,
  listNickLives,
  createNickLive,
  deleteNickLive,
  getSessions,
  startScan,
  stopScan,
  getScanStatus,
  getComments,
  saveModeratorCurl,
  getModeratorStatus,
  removeModerator,
  sendModeratorReply,
  autoReplyComments,
} from "../api/nickLive";
import {
  type NickLiveSettings,
  getNickLiveSettings,
  updateNickLiveSettings,
} from "../api/settings";
import KnowledgeProductsCard from "../components/KnowledgeProductsCard";
import CommentFeed from "../components/CommentFeed";

const { Title, Text } = Typography;
const { TextArea } = Input;

function formatDateTime(ts?: number): string {
  if (!ts) return "";
  const ms = ts > 1e12 ? ts : ts * 1000;
  return new Date(ms).toLocaleString("vi-VN");
}

function getDisplayName(c: CommentItem): string {
  return c.userName || c.username || c.nick_name || c.nickname || "Unknown";
}

function getCommentText(c: CommentItem): string {
  return c.content || c.comment || c.message || c.msg || "";
}

function LiveScan() {
  const [nickLives, setNickLives] = useState<NickLive[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [jsonInput, setJsonInput] = useState("");
  const [addLoading, setAddLoading] = useState(false);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessions, setSessions] = useState<LiveSession[]>([]);
  const [activeSession, setActiveSession] = useState<LiveSession | null>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [scanLoading, setScanLoading] = useState(false);

  // Moderator state
  const [curlInput, setCurlInput] = useState("");
  const [curlLoading, setCurlLoading] = useState(false);
  const [modStatus, setModStatus] = useState<ModeratorStatus | null>(null);
  const [replyText, setReplyText] = useState("");
  const [replyLoading, setReplyLoading] = useState(false);
  const [replyResults, setReplyResults] = useState<ModeratorReplyResult[]>([]);
  const [nickSettings, setNickSettings] = useState<NickLiveSettings | null>(
    null
  );
  const [settingsLoading, setSettingsLoading] = useState(false);

  // Comments ref for moderator reply (not state — avoids re-renders)
  const commentsRef = useRef<CommentItem[]>([]);

  const handleCommentsChange = useCallback((comments: CommentItem[]) => {
    commentsRef.current = comments;
  }, []);

  const loadNickLives = useCallback(async () => {
    try {
      const data = await listNickLives();
      setNickLives(data);
    } catch {
      message.error("Khong the tai danh sach nick live");
    }
  }, []);

  useEffect(() => {
    loadNickLives();
  }, [loadNickLives]);

  // Auto-detect scanning state on nick selection
  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;

    async function checkScanState() {
      try {
        const status = await getScanStatus(selectedId!);
        if (!cancelled && status.is_scanning) {
          setIsScanning(true);
        }
      } catch {
        // Not scanning or error — ignore
      }
    }

    checkScanState();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const handleAdd = useCallback(async () => {
    if (!jsonInput.trim()) {
      message.error("Vui long nhap JSON");
      return;
    }
    try {
      const parsed = JSON.parse(jsonInput);
      if (!parsed.user || !parsed.cookies) {
        message.error("JSON phai co truong 'user' va 'cookies'");
        return;
      }
      setAddLoading(true);
      await createNickLive({ user: parsed.user, cookies: parsed.cookies });
      message.success("Them nick live thanh cong");
      setJsonInput("");
      await loadNickLives();
    } catch (err: unknown) {
      if (err instanceof SyntaxError) {
        message.error("JSON khong hop le");
      } else {
        message.error("Khong the them nick live");
      }
    } finally {
      setAddLoading(false);
    }
  }, [jsonInput, loadNickLives]);

  const handleDelete = useCallback(
    async (id: number) => {
      try {
        await deleteNickLive(id);
        message.success("Da xoa nick live");
        if (selectedId === id) {
          setSelectedId(null);
          setSessions([]);
          setActiveSession(null);
          setIsScanning(false);
        }
        await loadNickLives();
      } catch {
        message.error("Khong the xoa nick live");
      }
    },
    [selectedId, loadNickLives]
  );

  const handleCheckSessions = useCallback(async () => {
    if (!selectedId) return;
    setSessionsLoading(true);
    try {
      const data = await getSessions(selectedId);
      setSessions(data.sessions);
      setActiveSession(data.active_session);
    } catch {
      message.error("Khong the kiem tra phien live");
    } finally {
      setSessionsLoading(false);
    }
  }, [selectedId]);

  const handleStartScan = useCallback(async () => {
    if (!selectedId || !activeSession) return;
    setScanLoading(true);
    try {
      await startScan(selectedId, activeSession.sessionId);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      if (detail !== "Already scanning") {
        message.error("Khong the bat dau quet");
        setScanLoading(false);
        return;
      }
    }
    setIsScanning(true);
    message.success("Bat dau quet comment");
    setScanLoading(false);
  }, [selectedId, activeSession]);

  const handleStopScan = useCallback(async () => {
    if (!selectedId) return;
    try {
      await stopScan(selectedId);
      setIsScanning(false);
      message.success("Da dung quet comment");
    } catch {
      message.error("Khong the dung quet");
    }
  }, [selectedId]);

  // --- Moderator handlers ---

  const loadModStatus = useCallback(async () => {
    if (!selectedId) return;
    try {
      const status = await getModeratorStatus(selectedId);
      setModStatus(status);
    } catch {
      setModStatus(null);
    }
  }, [selectedId]);

  const loadNickSettings = useCallback(async () => {
    if (!selectedId) return;
    try {
      const s = await getNickLiveSettings(selectedId);
      setNickSettings(s);
    } catch {
      setNickSettings(null);
    }
  }, [selectedId]);

  useEffect(() => {
    if (selectedId) {
      loadModStatus();
      loadNickSettings();
    } else {
      setModStatus(null);
      setNickSettings(null);
    }
  }, [selectedId, loadModStatus, loadNickSettings]);

  const handleToggleSetting = useCallback(
    async (
      field:
        | "ai_reply_enabled"
        | "auto_reply_enabled"
        | "auto_post_enabled"
        | "knowledge_reply_enabled",
      value: boolean
    ) => {
      if (!selectedId) return;
      setSettingsLoading(true);
      try {
        const updated = await updateNickLiveSettings(selectedId, {
          [field]: value,
        });
        setNickSettings(updated);
        message.success(value ? "Da bat" : "Da tat");
      } catch {
        message.error("Cap nhat that bai");
      } finally {
        setSettingsLoading(false);
      }
    },
    [selectedId]
  );

  const handleSaveCurl = useCallback(async () => {
    if (!selectedId || !curlInput.trim()) {
      message.error("Vui long dan cURL moderator");
      return;
    }
    setCurlLoading(true);
    try {
      await saveModeratorCurl(selectedId, curlInput);
      message.success("Luu cURL moderator thanh cong");
      setCurlInput("");
      await loadModStatus();
    } catch {
      message.error("Khong the parse cURL");
    } finally {
      setCurlLoading(false);
    }
  }, [selectedId, curlInput, loadModStatus]);

  const handleRemoveModerator = useCallback(async () => {
    if (!selectedId) return;
    try {
      await removeModerator(selectedId);
      message.success("Da xoa moderator");
      await loadModStatus();
    } catch {
      message.error("Khong the xoa moderator");
    }
  }, [selectedId, loadModStatus]);

  const handleSendReply = useCallback(
    async (comment: CommentItem) => {
      if (!selectedId || !replyText.trim()) {
        message.error("Nhap noi dung reply");
        return;
      }
      const guestName = getDisplayName(comment);
      const guestId =
        comment.streamerId ||
        comment.userId ||
        comment.user_id ||
        comment.uid ||
        0;
      setReplyLoading(true);
      try {
        const result = await sendModeratorReply(
          selectedId,
          guestName,
          guestId,
          replyText
        );
        if (result.success) {
          message.success(`Da reply @${guestName}`);
        } else {
          message.error(
            `Reply that bai: ${result.error || result.response || "Unknown error"}`
          );
        }
        setReplyResults((prev) => [...prev, result].slice(-100));
      } catch (err: unknown) {
        const detail = (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail;
        message.error(detail || "Khong the gui reply");
      } finally {
        setReplyLoading(false);
      }
    },
    [selectedId, replyText]
  );

  const handleAutoReply = useCallback(async () => {
    const currentComments = commentsRef.current;
    if (!selectedId || !replyText.trim() || currentComments.length === 0) {
      message.error("Can noi dung reply va comments");
      return;
    }
    setReplyLoading(true);
    try {
      const results = await autoReplyComments(
        selectedId,
        currentComments,
        replyText
      );
      const successCount = results.filter((r) => r.success).length;
      message.success(`Da reply ${successCount}/${results.length} comment`);
      setReplyResults(results);
    } catch {
      message.error("Auto reply that bai");
    } finally {
      setReplyLoading(false);
    }
  }, [selectedId, replyText]);

  const sessionColumns: ColumnsType<LiveSession> = [
    {
      title: "Session ID",
      dataIndex: "sessionId",
      key: "sessionId",
      width: 100,
    },
    { title: "Tieu de", dataIndex: "title", key: "title", ellipsis: true },
    {
      title: "Bat dau",
      dataIndex: "startTime",
      key: "startTime",
      render: (v: number) => formatDateTime(v),
      width: 180,
    },
    {
      title: "Trang thai",
      dataIndex: "status",
      key: "status",
      render: (v: number) =>
        v === 1 ? (
          <Tag color="green">Dang live</Tag>
        ) : (
          <Tag>Ket thuc</Tag>
        ),
      width: 100,
    },
    { title: "Luot xem", dataIndex: "views", key: "views", width: 100 },
    {
      title: "Nguoi xem",
      dataIndex: "viewers",
      key: "viewers",
      width: 100,
    },
    { title: "Comment", dataIndex: "comments", key: "comments", width: 100 },
  ];

  return (
    <div>
      <Title level={3}>Quet Comment Live Shopee</Title>

      {/* Section 1: Add NickLive */}
      <Card title="Them Nick Live" style={{ marginBottom: 16 }}>
        <TextArea
          rows={4}
          placeholder='Dan JSON vao day, vi du: {"user": {...}, "cookies": "..."}'
          value={jsonInput}
          onChange={(e) => setJsonInput(e.target.value)}
        />
        <Button
          type="primary"
          onClick={handleAdd}
          loading={addLoading}
          style={{ marginTop: 8 }}
        >
          Them
        </Button>
      </Card>

      {/* Section 2: NickLive List */}
      <Card title="Danh sach Nick Live" style={{ marginBottom: 16 }}>
        {nickLives.length === 0 ? (
          <Text type="secondary">Chua co nick live nao</Text>
        ) : (
          <Row gutter={[12, 12]}>
            {nickLives.map((nl) => (
              <Col key={nl.id} xs={24} sm={12} md={8} lg={6}>
                <Card
                  hoverable
                  size="small"
                  onClick={() => {
                    setSelectedId(nl.id);
                    setSessions([]);
                    setActiveSession(null);
                    setIsScanning(false);
                    setModStatus(null);
                    setReplyResults([]);
                  }}
                  style={{
                    border:
                      selectedId === nl.id
                        ? "2px solid #1677ff"
                        : "1px solid #d9d9d9",
                  }}
                  actions={[
                    <Popconfirm
                      key="delete"
                      title="Xac nhan xoa nick live nay?"
                      onConfirm={(e) => {
                        e?.stopPropagation();
                        handleDelete(nl.id);
                      }}
                      onCancel={(e) => e?.stopPropagation()}
                    >
                      <Button
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        size="small"
                        onClick={(e) => e.stopPropagation()}
                      >
                        Xoa
                      </Button>
                    </Popconfirm>,
                  ]}
                >
                  <Card.Meta
                    avatar={
                      <Avatar
                        src={nl.avatar}
                        icon={!nl.avatar ? <UserOutlined /> : undefined}
                      />
                    }
                    title={nl.name}
                    description={`User ID: ${nl.user_id}`}
                  />
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      {/* Section 3: Live Sessions */}
      {selectedId && (
        <Card title="Phien Live" style={{ marginBottom: 16 }}>
          <Button
            icon={<ReloadOutlined />}
            onClick={handleCheckSessions}
            loading={sessionsLoading}
          >
            Kiem tra phien live
          </Button>

          <Divider />

          {activeSession ? (
            <Card
              type="inner"
              title={
                <Space>
                  <Badge status="processing" />
                  <span>Phien live dang hoat dong</span>
                </Space>
              }
              style={{
                marginBottom: 16,
                borderColor: "#52c41a",
              }}
            >
              <Space direction="vertical" size="small">
                <Text strong>
                  {activeSession.title ||
                    `Session #${activeSession.sessionId}`}
                </Text>
                <Text>Session ID: {activeSession.sessionId}</Text>
                <Text>
                  Bat dau: {formatDateTime(activeSession.startTime)}
                </Text>
                <Space>
                  <Tag color="blue">Luot xem: {activeSession.views}</Tag>
                  <Tag color="cyan">Dang xem: {activeSession.viewers}</Tag>
                  <Tag color="purple">
                    Dinh: {activeSession.peakViewers}
                  </Tag>
                </Space>
              </Space>
              <div style={{ marginTop: 12 }}>
                <Button
                  type="primary"
                  size="large"
                  icon={<PlayCircleOutlined />}
                  onClick={handleStartScan}
                  loading={scanLoading}
                  disabled={isScanning}
                  style={{
                    backgroundColor: "#52c41a",
                    borderColor: "#52c41a",
                  }}
                >
                  Bat dau quet comment
                </Button>
              </div>
            </Card>
          ) : (
            sessions.length > 0 && (
              <Alert
                type="warning"
                message="Khong co phien live nao dang hoat dong"
                style={{ marginBottom: 16 }}
                showIcon
              />
            )
          )}

          {sessions.length > 0 && (
            <Table
              dataSource={sessions}
              columns={sessionColumns}
              rowKey="sessionId"
              size="small"
              pagination={false}
              scroll={{ x: 800 }}
            />
          )}
        </Card>
      )}

      {/* Section 4: Comment Feed — isolated component */}
      <CommentFeed
        nickLiveId={selectedId}
        isScanning={isScanning}
        onStopScan={handleStopScan}
        onCommentsChange={handleCommentsChange}
      />

      {/* Section 5: Moderator - only when nick selected */}
      {selectedId && (
        <>
          <Divider />
          <Title level={4}>Moderator - Reply Comment</Title>

          {!activeSession ? (
            <Alert
              type="warning"
              message="Khong co phien live dang hoat dong"
              description="Can co phien live dang hoat dong de su dung moderator. Hay kiem tra phien live truoc."
              showIcon
              style={{ marginBottom: 16 }}
            />
          ) : (
            <>
              {/* Save cURL */}
              <Card
                title="Luu cURL Moderator"
                style={{ marginBottom: 16 }}
                extra={
                  modStatus?.configured ? (
                    <Space>
                      <Tag color="green">Da cau hinh</Tag>
                      <Tag>Host: {modStatus.host_id || "N/A"}</Tag>
                      <Popconfirm
                        title="Xoa moderator?"
                        onConfirm={handleRemoveModerator}
                      >
                        <Button
                          type="text"
                          danger
                          icon={<DeleteOutlined />}
                          size="small"
                        >
                          Xoa
                        </Button>
                      </Popconfirm>
                    </Space>
                  ) : (
                    <Tag color="red">Chua cau hinh</Tag>
                  )
                }
              >
                <TextArea
                  rows={4}
                  placeholder="Dan cURL moderator vao day (curl https://live.shopee.vn/api/v1/session/.../message ...)"
                  value={curlInput}
                  onChange={(e) => setCurlInput(e.target.value)}
                />
                <Button
                  type="primary"
                  onClick={handleSaveCurl}
                  loading={curlLoading}
                  style={{ marginTop: 8 }}
                >
                  {modStatus?.configured ? "Cap nhat cURL" : "Luu cURL"}
                </Button>
              </Card>

              {/* Automation Settings Card */}
              {modStatus?.configured && (
                <Card
                  title="Cai dat tu dong"
                  style={{ marginBottom: 16 }}
                >
                  <Space direction="vertical" style={{ width: "100%" }}>
                    <Space>
                      <Switch
                        checked={nickSettings?.ai_reply_enabled ?? false}
                        onChange={(v) =>
                          handleToggleSetting("ai_reply_enabled", v)
                        }
                        loading={settingsLoading}
                        disabled={!isScanning}
                      />
                      <span>Bat AI Reply</span>
                      {!isScanning && (
                        <Tag icon={<InfoCircleOutlined />} color="warning">
                          Can dang quet
                        </Tag>
                      )}
                    </Space>
                    <Space>
                      <Switch
                        checked={
                          nickSettings?.knowledge_reply_enabled ?? false
                        }
                        onChange={(v) =>
                          handleToggleSetting("knowledge_reply_enabled", v)
                        }
                        loading={settingsLoading}
                        disabled={!isScanning}
                      />
                      <span>
                        Bat Knowledge Reply (AI + du lieu san pham)
                      </span>
                      {!isScanning && (
                        <Tag icon={<InfoCircleOutlined />} color="warning">
                          Can dang quet
                        </Tag>
                      )}
                    </Space>
                    <Divider style={{ margin: "8px 0" }} />
                    <Space>
                      <Switch
                        checked={nickSettings?.auto_reply_enabled ?? false}
                        onChange={(v) =>
                          handleToggleSetting("auto_reply_enabled", v)
                        }
                        loading={settingsLoading}
                        disabled={!isScanning}
                      />
                      <span>
                        Bat Auto-reply (tu dong reply comment moi)
                      </span>
                    </Space>
                    <Space>
                      <Switch
                        checked={nickSettings?.auto_post_enabled ?? false}
                        onChange={(v) =>
                          handleToggleSetting("auto_post_enabled", v)
                        }
                        loading={settingsLoading}
                        disabled={!isScanning}
                      />
                      <span>Bat Auto-post (dang comment theo lich)</span>
                    </Space>

                    {nickSettings?.knowledge_reply_enabled && (
                      <Tag color="gold">
                        Dang reply bang Knowledge AI (san pham)
                      </Tag>
                    )}
                    {nickSettings?.ai_reply_enabled &&
                      !nickSettings?.knowledge_reply_enabled && (
                        <Tag color="purple">Dang reply bang AI</Tag>
                      )}
                    {nickSettings?.auto_reply_enabled &&
                      !nickSettings?.ai_reply_enabled &&
                      !nickSettings?.knowledge_reply_enabled && (
                        <Tag color="blue">
                          Dang reply bang template ngau nhien
                        </Tag>
                      )}
                    {nickSettings?.auto_post_enabled && (
                      <Tag color="green">Dang dang comment theo lich</Tag>
                    )}
                  </Space>
                </Card>
              )}

              {/* Knowledge Products Card — isolated component */}
              {modStatus?.configured && (
                <KnowledgeProductsCard nickLiveId={selectedId} />
              )}

              {/* Reply Controls - only when scanning AND moderator configured */}
              {isScanning && modStatus?.configured && (
                <Card title="Reply Comment" style={{ marginBottom: 16 }}>
                  <Space direction="vertical" style={{ width: "100%" }}>
                    <Input
                      placeholder="Noi dung reply (VD: Cam on ban da hoi!)"
                      value={replyText}
                      onChange={(e) => setReplyText(e.target.value)}
                      onPressEnter={handleAutoReply}
                    />
                    <Button
                      type="primary"
                      onClick={handleAutoReply}
                      loading={replyLoading}
                      disabled={!replyText.trim()}
                    >
                      Auto Reply tat ca
                    </Button>
                  </Space>

                  {/* Reply per comment — uses commentsRef */}
                  {replyText.trim() && commentsRef.current.length > 0 && (
                    <div
                      style={{
                        marginTop: 16,
                        maxHeight: 300,
                        overflowY: "auto",
                      }}
                    >
                      <Text strong>Reply tung comment:</Text>
                      {commentsRef.current.slice(-20).map((c, idx) => (
                        <div
                          key={c.id || idx}
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            padding: "4px 8px",
                            borderBottom: "1px solid #f0f0f0",
                          }}
                        >
                          <div>
                            <Text strong style={{ color: "#1677ff" }}>
                              {getDisplayName(c)}:
                            </Text>{" "}
                            <Text>{getCommentText(c)}</Text>
                          </div>
                          <Button
                            size="small"
                            type="link"
                            loading={replyLoading}
                            onClick={() => handleSendReply(c)}
                          >
                            Reply
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Reply Results */}
                  {replyResults.length > 0 && (
                    <div style={{ marginTop: 16 }}>
                      <Text strong>Ket qua reply:</Text>
                      {replyResults.slice(-10).map((r, idx) => (
                        <div key={idx} style={{ padding: "2px 8px" }}>
                          <Tag color={r.success ? "green" : "red"}>
                            {r.success ? "OK" : "FAIL"}
                          </Tag>
                          <Text>
                            @{r.guest} -{" "}
                            {r.success ? r.reply : r.error}
                          </Text>
                        </div>
                      ))}
                    </div>
                  )}
                </Card>
              )}

              {/* Show message when moderator configured but not scanning */}
              {!isScanning && modStatus?.configured && (
                <Alert
                  type="info"
                  message="Bat dau quet comment de su dung reply"
                  showIcon
                  style={{ marginBottom: 16 }}
                />
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

export default LiveScan;
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors

- [ ] **Step 3: Test in browser**

Run: `cd frontend && npm run dev`

Manual verification:
1. Select a nick → check sessions loads
2. Start scan → verify SSE connects (comment feed appears, no polling in network tab)
3. F5 → re-select nick → verify `isScanning` auto-detected from backend
4. Verify comments appear in real-time without page jank
5. Verify product card does NOT re-render on new comments
6. Verify moderator reply still works

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/LiveScan.tsx
git commit -m "refactor: LiveScan uses SSE + isolated CommentFeed and KnowledgeProducts"
```

---

### Task 6: Handle SSE API key authentication

**Files:**
- Modify: `backend/app/routers/nick_live.py:136-154`

The SSE endpoint uses `EventSourceResponse` but the frontend `EventSource` API cannot set custom headers. If `APP_API_KEY` is configured, SSE will fail with 403. Add query param support.

- [ ] **Step 1: Check if backend has API key dependency on the SSE route**

Read: `backend/app/routers/nick_live.py` lines 1-30 and the SSE route to see if `require_api_key` is applied.

Run: `cd backend && grep -n "require_api_key\|Depends.*api_key" app/routers/nick_live.py | head -10`

If the router uses a global dependency for API key, the SSE endpoint needs a query param fallback.

- [ ] **Step 2: Add query param API key support to the dependency**

Read `backend/app/dependencies.py` to understand current auth. If it only checks headers, add query param fallback:

Modify `backend/app/dependencies.py`:

```python
from fastapi import Depends, HTTPException, Query, Request

def require_api_key(
    request: Request,
    api_key_query: str | None = Query(None, alias="api_key"),
) -> None:
    """Check API key from header or query param (for SSE/EventSource)."""
    import os
    expected = os.getenv("APP_API_KEY", "")
    if not expected:
        return  # No key configured — skip auth

    # Try header first, then query param
    provided = request.headers.get("X-API-Key") or api_key_query
    if provided != expected:
        raise HTTPException(status_code=403, detail="Invalid API key")
```

- [ ] **Step 3: Verify backend starts**

Run: `cd backend && python -c "from app.main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/dependencies.py
git commit -m "feat: support API key via query param for SSE EventSource"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | `useSSEComments` hook | NEW: `hooks/useSSEComments.ts` |
| 2 | `useKnowledgeProducts` hook | NEW: `hooks/useKnowledgeProducts.ts` |
| 3 | `CommentFeed` component | NEW: `components/CommentFeed.tsx` |
| 4 | Refactor `KnowledgeProductsCard` | MODIFY: `components/KnowledgeProductsCard.tsx` |
| 5 | Refactor `LiveScan.tsx` | MODIFY: `pages/LiveScan.tsx` |
| 6 | SSE API key query param | MODIFY: `backend/app/dependencies.py` |
