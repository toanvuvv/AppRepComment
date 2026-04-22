import { useCallback, useEffect, useState } from "react";
import * as api from "../api/seeding";

export function useSeedingLogs(logSessionId: number | null) {
  const [logs, setLogs] = useState<api.SeedingLog[]>([]);

  const refresh = useCallback(async () => {
    if (logSessionId == null) return;
    setLogs(await api.listLogs(logSessionId));
  }, [logSessionId]);

  useEffect(() => {
    refresh();
    if (logSessionId == null) return;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [logSessionId, refresh]);

  return { logs, refresh };
}
