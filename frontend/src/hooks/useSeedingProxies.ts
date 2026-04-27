import { useCallback, useEffect, useState } from "react";

import {
  listProxies,
  createProxy,
  updateProxy,
  deleteProxy,
  importProxies,
  assignProxies,
  getProxySetting,
  setProxySetting,
  type ProxyAssignPayload,
  type ProxyAssignResult,
  type ProxyCreatePayload,
  type ProxyImportPayload,
  type ProxyImportResult,
  type ProxyUpdatePatch,
  type SeedingProxy,
} from "../api/seedingProxy";

export interface UseSeedingProxiesResult {
  proxies: SeedingProxy[];
  requireProxy: boolean;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  create: (payload: ProxyCreatePayload) => Promise<void>;
  update: (id: number, patch: ProxyUpdatePatch) => Promise<void>;
  remove: (id: number) => Promise<void>;
  importBulk: (payload: ProxyImportPayload) => Promise<ProxyImportResult>;
  assign: (payload: ProxyAssignPayload) => Promise<ProxyAssignResult>;
  setRequireProxy: (value: boolean) => Promise<void>;
}

export function useSeedingProxies(): UseSeedingProxiesResult {
  const [proxies, setProxies] = useState<SeedingProxy[]>([]);
  const [requireProxy, setRequireProxyState] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, setting] = await Promise.all([
        listProxies(),
        getProxySetting(),
      ]);
      setProxies(list);
      setRequireProxyState(setting.require_proxy);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const create = async (payload: ProxyCreatePayload): Promise<void> => {
    await createProxy(payload);
    await refresh();
  };

  const update = async (
    id: number,
    patch: ProxyUpdatePatch,
  ): Promise<void> => {
    await updateProxy(id, patch);
    await refresh();
  };

  const remove = async (id: number): Promise<void> => {
    await deleteProxy(id);
    await refresh();
  };

  const importBulk = async (
    payload: ProxyImportPayload,
  ): Promise<ProxyImportResult> => {
    const result = await importProxies(payload);
    await refresh();
    return result;
  };

  const assign = async (
    payload: ProxyAssignPayload,
  ): Promise<ProxyAssignResult> => {
    const result = await assignProxies(payload);
    await refresh();
    return result;
  };

  const setRequireProxy = async (value: boolean): Promise<void> => {
    await setProxySetting({ require_proxy: value });
    setRequireProxyState(value);
  };

  return {
    proxies, requireProxy, loading, error,
    refresh, create, update, remove, importBulk, assign, setRequireProxy,
  };
}
