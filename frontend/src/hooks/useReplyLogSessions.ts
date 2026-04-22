import { useCallback, useEffect, useRef, useState } from "react";
import { listReplyLogSessions, type ReplyLogSession } from "../api/replyLogs";

const POLL_INTERVAL_MS = 2500;

export interface UseReplyLogSessionsResult {
  sessions: ReplyLogSession[];
  refresh: () => void;
}

export function useReplyLogSessions(
  nickLiveId: number | null,
  enabled: boolean
): UseReplyLogSessionsResult {
  const [sessions, setSessions] = useState<ReplyLogSession[]>([]);
  const cancelledRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchOnce = useCallback(async () => {
    if (nickLiveId === null) return;
    try {
      const data = await listReplyLogSessions(nickLiveId);
      if (cancelledRef.current) return;
      setSessions(data);
    } catch {
      // Silent — polling retries
    }
  }, [nickLiveId]);

  const refresh = useCallback(() => {
    fetchOnce();
  }, [fetchOnce]);

  useEffect(() => {
    cancelledRef.current = false;

    if (!enabled || nickLiveId === null) {
      setSessions([]);
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
  }, [enabled, nickLiveId, fetchOnce]);

  return { sessions, refresh };
}
