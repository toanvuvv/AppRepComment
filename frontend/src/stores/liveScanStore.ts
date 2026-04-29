import { create } from "zustand";
import type { CommentItem, LiveSession, ScanStats } from "../api/nickLive";
import { startScan, stopScan, getComments } from "../api/nickLive";
import { withAuthQuery } from "../api/client";

const COMMENT_BUFFER_MAX = 500;
const SSE_INITIAL_RETRY_MS = 1000;
const SSE_MAX_RETRY_MS = 10000;

export interface SessionEntry {
  active: LiveSession | null;
  all: LiveSession[];
  lastFetched: number;
  error: string | null;
}

interface SSEHandle {
  source: EventSource;
  retryTimer: ReturnType<typeof setTimeout> | null;
  retryDelay: number;
  cancelled: boolean;
}

interface LiveScanState {
  sessionsByNick: Record<number, SessionEntry>;
  scanningNickIds: Set<number>;
  commentsByNick: Record<number, CommentItem[]>;
  miniStatsByNick: Record<number, ScanStats>;
  cookieExpiredByNick: Record<number, boolean>;
  sseConnected: Record<number, boolean>;
  sseHandles: Record<number, SSEHandle>;

  upsertSession: (nickId: number, entry: Partial<SessionEntry>) => void;
  setScanning: (nickId: number, value: boolean) => void;
  appendComment: (nickId: number, comment: CommentItem) => void;
  setComments: (nickId: number, comments: CommentItem[]) => void;
  clearComments: (nickId: number) => void;
  setMiniStats: (nickId: number, stats: ScanStats) => void;
  setCookieExpired: (nickId: number, value: boolean) => void;

  startScanFor: (nickId: number, sessionId: number) => Promise<void>;
  stopScanFor: (nickId: number) => Promise<void>;
  openSSE: (nickId: number) => void;
  closeSSE: (nickId: number) => void;
}

export const useLiveScanStore = create<LiveScanState>((set, get) => ({
  sessionsByNick: {},
  scanningNickIds: new Set<number>(),
  commentsByNick: {},
  miniStatsByNick: {},
  cookieExpiredByNick: {},
  sseConnected: {},
  sseHandles: {},

  upsertSession: (nickId, entry) =>
    set((s) => ({
      sessionsByNick: {
        ...s.sessionsByNick,
        [nickId]: {
          active: entry.active ?? s.sessionsByNick[nickId]?.active ?? null,
          all: entry.all ?? s.sessionsByNick[nickId]?.all ?? [],
          lastFetched: entry.lastFetched ?? Date.now(),
          error: entry.error ?? null,
        },
      },
    })),

  setScanning: (nickId, value) =>
    set((s) => {
      const next = new Set(s.scanningNickIds);
      if (value) next.add(nickId);
      else next.delete(nickId);
      return { scanningNickIds: next };
    }),

  appendComment: (nickId, comment) =>
    set((s) => {
      const prev = s.commentsByNick[nickId] ?? [];
      const next = prev.length >= COMMENT_BUFFER_MAX
        ? [...prev.slice(prev.length - COMMENT_BUFFER_MAX + 1), comment]
        : [...prev, comment];
      return { commentsByNick: { ...s.commentsByNick, [nickId]: next } };
    }),

  setComments: (nickId, comments) =>
    set((s) => ({
      commentsByNick: {
        ...s.commentsByNick,
        [nickId]: comments.slice(-COMMENT_BUFFER_MAX),
      },
    })),

  clearComments: (nickId) =>
    set((s) => {
      const next = { ...s.commentsByNick };
      delete next[nickId];
      return { commentsByNick: next };
    }),

  setMiniStats: (nickId, stats) =>
    set((s) => ({ miniStatsByNick: { ...s.miniStatsByNick, [nickId]: stats } })),

  setCookieExpired: (nickId, value) =>
    set((s) => ({
      cookieExpiredByNick: { ...s.cookieExpiredByNick, [nickId]: value },
    })),

  startScanFor: async (nickId, sessionId) => {
    try {
      await startScan(nickId, sessionId);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      if (detail !== "Already scanning") throw err;
    }
    get().setScanning(nickId, true);
    get().setCookieExpired(nickId, false);
    get().openSSE(nickId);
  },

  stopScanFor: async (nickId) => {
    try {
      await stopScan(nickId);
    } catch {
      // best-effort; we still tear down local state
    }
    get().setScanning(nickId, false);
    get().closeSSE(nickId);
  },

  openSSE: (nickId) => {
    const existing = get().sseHandles[nickId];
    if (existing) return;

    const handle: SSEHandle = {
      source: null as unknown as EventSource,
      retryTimer: null,
      retryDelay: SSE_INITIAL_RETRY_MS,
      cancelled: false,
    };

    const connect = () => {
      if (handle.cancelled) return;
      const url = withAuthQuery(`/api/nick-lives/${nickId}/comments/stream`);
      const es = new EventSource(url);
      handle.source = es;

      es.onopen = () => {
        if (handle.cancelled) {
          es.close();
          return;
        }
        set((s) => ({ sseConnected: { ...s.sseConnected, [nickId]: true } }));
        handle.retryDelay = SSE_INITIAL_RETRY_MS;
      };

      es.addEventListener("comment", (event: MessageEvent) => {
        if (handle.cancelled) return;
        try {
          const c = JSON.parse(event.data) as CommentItem;
          get().appendComment(nickId, c);
        } catch {
          // ignore malformed
        }
      });

      es.addEventListener("cookie_expired", () => {
        get().setCookieExpired(nickId, true);
        get().stopScanFor(nickId);
      });

      es.addEventListener("ping", () => { /* keep-alive */ });

      es.onerror = () => {
        if (handle.cancelled) return;
        es.close();
        set((s) => ({ sseConnected: { ...s.sseConnected, [nickId]: false } }));
        const delay = handle.retryDelay;
        handle.retryDelay = Math.min(delay * 2, SSE_MAX_RETRY_MS);
        handle.retryTimer = setTimeout(() => {
          handle.retryTimer = null;
          connect();
        }, delay);
      };
    };

    set((s) => ({ sseHandles: { ...s.sseHandles, [nickId]: handle } }));

    // Hydrate with existing comments before opening stream
    getComments(nickId)
      .then((existing) => {
        if (!handle.cancelled) get().setComments(nickId, existing);
      })
      .catch(() => { /* non-fatal */ })
      .finally(() => connect());
  },

  closeSSE: (nickId) => {
    const handle = get().sseHandles[nickId];
    if (!handle) return;
    handle.cancelled = true;
    if (handle.retryTimer !== null) clearTimeout(handle.retryTimer);
    if (handle.source) handle.source.close();
    set((s) => {
      const handles = { ...s.sseHandles };
      delete handles[nickId];
      const conn = { ...s.sseConnected };
      delete conn[nickId];
      return { sseHandles: handles, sseConnected: conn };
    });
  },
}));
