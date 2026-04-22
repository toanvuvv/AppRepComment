import { useCallback, useEffect, useRef, useState } from "react";
import {
  listReplyLogs,
  getReplyLogStats,
  type ReplyLog,
  type ReplyLogStats,
} from "../api/replyLogs";

const POLL_INTERVAL_MS = 2500;
const LOG_LIMIT = 200;

export interface ReplyLogIndex {
  /** Map key: `${guest_id}|${comment_text}` → most recent log */
  byCommentKey: Map<string, ReplyLog>;
  /** Fallback map: `${guest_id}` → most recent log */
  byGuest: Map<string, ReplyLog>;
}

export interface UseReplyLogsResult {
  logs: ReplyLog[];
  stats: ReplyLogStats | null;
  index: ReplyLogIndex;
  refresh: () => void;
}

function buildIndex(logs: ReplyLog[]): ReplyLogIndex {
  const byCommentKey = new Map<string, ReplyLog>();
  const byGuest = new Map<string, ReplyLog>();
  // logs are newest-first; iterate in reverse so newest wins via overwrite
  for (let i = logs.length - 1; i >= 0; i--) {
    const log = logs[i];
    if (log.guest_id && log.comment_text) {
      byCommentKey.set(`${log.guest_id}|${log.comment_text}`, log);
    }
    if (log.guest_id) {
      byGuest.set(log.guest_id, log);
    }
  }
  return { byCommentKey, byGuest };
}

export function buildLogKey(
  guestId: string | number | undefined | null,
  commentText: string | undefined | null
): string | null {
  if (guestId === undefined || guestId === null || guestId === "" || guestId === 0) {
    return null;
  }
  if (!commentText) return null;
  return `${guestId}|${commentText}`;
}

export function useReplyLogs(
  nickLiveId: number | null,
  enabled: boolean,
  sessionId: number | null = null
): UseReplyLogsResult {
  const [logs, setLogs] = useState<ReplyLog[]>([]);
  const [stats, setStats] = useState<ReplyLogStats | null>(null);
  const [index, setIndex] = useState<ReplyLogIndex>(() => ({
    byCommentKey: new Map(),
    byGuest: new Map(),
  }));

  const cancelledRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchOnce = useCallback(async () => {
    if (nickLiveId === null) return;
    try {
      const [logList, statResp] = await Promise.all([
        listReplyLogs({
          nick_live_id: nickLiveId,
          session_id: sessionId ?? undefined,
          limit: LOG_LIMIT,
        }),
        getReplyLogStats(nickLiveId),
      ]);
      if (cancelledRef.current) return;
      setLogs(logList);
      setStats(statResp);
      setIndex(buildIndex(logList));
    } catch {
      // Silent — polling will retry
    }
  }, [nickLiveId, sessionId]);

  const refresh = useCallback(() => {
    fetchOnce();
  }, [fetchOnce]);

  useEffect(() => {
    cancelledRef.current = false;

    if (!enabled || nickLiveId === null) {
      setLogs([]);
      setStats(null);
      setIndex({ byCommentKey: new Map(), byGuest: new Map() });
      return;
    }

    async function loop() {
      await fetchOnce();
      if (cancelledRef.current) return;
      timerRef.current = setTimeout(loop, POLL_INTERVAL_MS);
    }

    loop();

    return () => {
      cancelledRef.current = true;
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [enabled, nickLiveId, sessionId, fetchOnce]);

  return { logs, stats, index, refresh };
}
