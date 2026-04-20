import { useState, useEffect, useRef, useCallback } from "react";
import { CommentItem, getComments } from "../api/nickLive";
import { withTokenQuery } from "../api/client";

const INITIAL_RETRY_DELAY = 1000;
const MAX_RETRY_DELAY = 10000;

interface UseSSECommentsResult {
  comments: CommentItem[];
  commentCount: number;
  isConnected: boolean;
}

export function useSSEComments(
  nickLiveId: number | null,
  isScanning: boolean
): UseSSECommentsResult {
  const [comments, setComments] = useState<CommentItem[]>([]);
  const [isConnected, setIsConnected] = useState(false);

  const eventSourceRef = useRef<EventSource | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryDelayRef = useRef<number>(INITIAL_RETRY_DELAY);

  const cleanup = useCallback(() => {
    if (retryTimerRef.current !== null) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    if (eventSourceRef.current !== null) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setIsConnected(false);
    retryDelayRef.current = INITIAL_RETRY_DELAY;
  }, []);

  useEffect(() => {
    if (!isScanning || nickLiveId === null) {
      cleanup();
      setComments([]);
      return;
    }

    let cancelled = false;

    function connect() {
      if (cancelled) return;

      const url = withTokenQuery(`/api/nick-lives/${nickLiveId}/comments/stream`);

      const es = new EventSource(url);
      eventSourceRef.current = es;

      es.onopen = () => {
        if (cancelled) {
          es.close();
          return;
        }
        setIsConnected(true);
        retryDelayRef.current = INITIAL_RETRY_DELAY;
      };

      es.addEventListener("comment", (event: MessageEvent) => {
        if (cancelled) return;
        try {
          const comment = JSON.parse(event.data) as CommentItem;
          setComments((prev) => [...prev, comment]);
        } catch {
          // Ignore malformed comment data
        }
      });

      es.addEventListener("ping", () => {
        // Keep-alive — no action needed
      });

      es.onerror = () => {
        if (cancelled) return;
        es.close();
        eventSourceRef.current = null;
        setIsConnected(false);

        const delay = retryDelayRef.current;
        retryDelayRef.current = Math.min(delay * 2, MAX_RETRY_DELAY);

        retryTimerRef.current = setTimeout(() => {
          retryTimerRef.current = null;
          connect();
        }, delay);
      };
    }

    async function init() {
      try {
        const existing = await getComments(nickLiveId as number);
        if (!cancelled) {
          setComments(existing);
        }
      } catch {
        // Non-fatal — proceed to SSE even if initial load fails
      }

      if (!cancelled) {
        connect();
      }
    }

    init();

    return () => {
      cancelled = true;
      cleanup();
      setComments([]);
    };
  }, [isScanning, nickLiveId, cleanup]);

  return {
    comments,
    commentCount: comments.length,
    isConnected,
  };
}
