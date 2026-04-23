import { useCallback, useEffect, useState } from "react";
import {
  listClones,
  createClone,
  updateClone,
  deleteClone,
  reviveClone,
  type SeedingClone,
  type CreateClonePayload,
  type UpdateClonePatch,
} from "../api/seeding";

export interface UseSeedingClonesResult {
  clones: SeedingClone[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  create: (payload: CreateClonePayload) => Promise<void>;
  update: (id: number, patch: UpdateClonePatch) => Promise<void>;
  remove: (id: number) => Promise<void>;
  revive: (id: number) => Promise<void>;
}

export function useSeedingClones(): UseSeedingClonesResult {
  const [clones, setClones] = useState<SeedingClone[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setClones(await listClones());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const create = async (payload: CreateClonePayload): Promise<void> => {
    await createClone(payload);
    await refresh();
  };

  const update = async (
    id: number,
    patch: UpdateClonePatch
  ): Promise<void> => {
    await updateClone(id, patch);
    await refresh();
  };

  const remove = async (id: number): Promise<void> => {
    await deleteClone(id);
    await refresh();
  };

  const revive = async (id: number): Promise<void> => {
    await reviveClone(id);
    await refresh();
  };

  return { clones, loading, error, refresh, create, update, remove, revive };
}
