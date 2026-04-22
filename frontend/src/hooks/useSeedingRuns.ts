import { useCallback, useEffect, useState } from "react";
import * as api from "../api/seeding";

export function useSeedingRuns() {
  const [runs, setRuns] = useState<api.SeedingRunStatus[]>([]);

  const refresh = useCallback(async () => {
    setRuns(await api.autoRunning());
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  const start = async (p: Parameters<typeof api.autoStart>[0]) => {
    const r = await api.autoStart(p);
    await refresh();
    return r;
  };

  const stop = async (id: number) => {
    await api.autoStop(id);
    await refresh();
  };

  return { runs, start, stop, refresh };
}
