import { useEffect } from "react";
import { getScanStats } from "../api/nickLive";
import { useLiveScanStore } from "../stores/liveScanStore";

const POLL_INTERVAL_MS = 15_000;
const WINDOW_SECONDS = 300;
const MAX_PARALLEL = 5;

async function fetchInBatches(
  ids: number[],
  setStats: (id: number, stats: Awaited<ReturnType<typeof getScanStats>>) => void
): Promise<void> {
  for (let i = 0; i < ids.length; i += MAX_PARALLEL) {
    const slice = ids.slice(i, i + MAX_PARALLEL);
    await Promise.all(
      slice.map(async (id) => {
        try {
          const stats = await getScanStats(id, WINDOW_SECONDS);
          setStats(id, stats);
        } catch {
          // ignore per-nick errors
        }
      })
    );
  }
}

export function useScanStatsPoll(scanningNickIds: number[]): void {
  const setMiniStats = useLiveScanStore((s) => s.setMiniStats);
  const idsKey = scanningNickIds.slice().sort((a, b) => a - b).join(",");

  useEffect(() => {
    if (idsKey.length === 0) return;
    const ids = idsKey.split(",").map(Number).filter(Boolean);
    let cancelled = false;

    async function tick() {
      if (cancelled) return;
      await fetchInBatches(ids, setMiniStats);
    }

    tick();
    const handle = setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(handle);
    };
  }, [idsKey, setMiniStats]);
}
