import { useCallback, useEffect, useState } from "react";
import {
  listTemplates,
  createTemplate,
  updateTemplate,
  deleteTemplate,
  bulkCreateTemplates,
  type SeedingTemplate,
  type UpdateTemplatePatch,
} from "../api/seeding";

export interface UseSeedingTemplatesResult {
  templates: SeedingTemplate[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  create: (content: string, enabled?: boolean) => Promise<void>;
  update: (id: number, patch: UpdateTemplatePatch) => Promise<void>;
  remove: (id: number) => Promise<void>;
  bulkCreate: (lines: string[]) => Promise<void>;
}

export function useSeedingTemplates(): UseSeedingTemplatesResult {
  const [templates, setTemplates] = useState<SeedingTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setTemplates(await listTemplates());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const create = async (
    content: string,
    enabled = true
  ): Promise<void> => {
    await createTemplate(content, enabled);
    await refresh();
  };

  const update = async (
    id: number,
    patch: UpdateTemplatePatch
  ): Promise<void> => {
    await updateTemplate(id, patch);
    await refresh();
  };

  const remove = async (id: number): Promise<void> => {
    await deleteTemplate(id);
    await refresh();
  };

  const bulkCreate = async (lines: string[]): Promise<void> => {
    await bulkCreateTemplates(lines);
    await refresh();
  };

  return {
    templates,
    loading,
    error,
    refresh,
    create,
    update,
    remove,
    bulkCreate,
  };
}
