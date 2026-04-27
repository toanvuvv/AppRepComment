import { useEffect, useRef } from "react";
import { listSessionsBatch } from "../api/nickLive";
import { useLiveScanStore } from "../stores/liveScanStore";

const POLL_INTERVAL_MS = 60_000;

export function useNickLiveSessionsPoll(nickIds: number[], enabled = true): void {
  const upsertSession = useLiveScanStore((s) => s.upsertSession);
  const stopScanFor = useLiveScanStore((s) => s.stopScanFor);
  const scanningNickIds = useLiveScanStore((s) => s.scanningNickIds);

  const idsKey = nickIds.slice().sort((a, b) => a - b).join(",");
  const scanningRef = useRef(scanningNickIds);
  scanningRef.current = scanningNickIds;

  useEffect(() => {
    if (!enabled || idsKey.length === 0) return;
    const ids = idsKey.split(",").map(Number).filter(Boolean);
    let cancelled = false;

    async function tick() {
      try {
        const res = await listSessionsBatch(ids);
        if (cancelled) return;
        for (const id of ids) {
          const entry = res.sessions[String(id)];
          if (!entry) {
            upsertSession(id, { active: null, all: [], error: null });
            continue;
          }
          upsertSession(id, {
            active: entry.active_session,
            all: entry.all_sessions,
            error: entry.error ?? null,
          });
          if (
            scanningRef.current.has(id) &&
            entry.active_session === null
          ) {
            stopScanFor(id);
          }
        }
      } catch {
        // network error — skip this tick
      }
    }

    tick();
    const handle = setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(handle);
    };
  }, [idsKey, enabled, upsertSession, stopScanFor]);
}
