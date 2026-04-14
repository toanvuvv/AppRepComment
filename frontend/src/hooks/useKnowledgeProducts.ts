import { useCallback, useEffect, useState } from "react";
import { message } from "antd";
import {
  deleteKnowledgeProducts,
  getKnowledgeProducts,
  importKnowledgeProducts,
  KnowledgeProduct,
} from "../api/knowledge";

interface UseKnowledgeProductsReturn {
  products: KnowledgeProduct[];
  loading: boolean;
  importLoading: boolean;
  loadProducts: () => Promise<void>;
  handleImport: (rawJson: string) => Promise<boolean>;
  handleDeleteAll: () => Promise<void>;
}

export function useKnowledgeProducts(
  nickLiveId: number | null
): UseKnowledgeProductsReturn {
  const [products, setProducts] = useState<KnowledgeProduct[]>([]);
  const [loading, setLoading] = useState(false);
  const [importLoading, setImportLoading] = useState(false);

  const loadProducts = useCallback(async () => {
    if (!nickLiveId) return;
    setLoading(true);
    try {
      const data = await getKnowledgeProducts(nickLiveId);
      setProducts(data);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [nickLiveId]);

  useEffect(() => {
    loadProducts();
  }, [loadProducts]);

  const handleImport = useCallback(
    async (rawJson: string): Promise<boolean> => {
      if (!nickLiveId || !rawJson.trim()) {
        message.warning("Paste JSON data trước");
        return false;
      }
      setImportLoading(true);
      try {
        const data = await importKnowledgeProducts(nickLiveId, rawJson);
        setProducts(data);
        message.success(`Import thành công ${data.length} sản phẩm`);
        return true;
      } catch (err: unknown) {
        const errorMsg =
          err instanceof Error ? err.message : "Import thất bại";
        message.error(errorMsg);
        return false;
      } finally {
        setImportLoading(false);
      }
    },
    [nickLiveId]
  );

  const handleDeleteAll = useCallback(async (): Promise<void> => {
    if (!nickLiveId) return;
    try {
      await deleteKnowledgeProducts(nickLiveId);
      setProducts([]);
      message.success("Đã xóa tất cả sản phẩm");
    } catch {
      message.error("Xóa thất bại");
    }
  }, [nickLiveId]);

  return {
    products,
    loading,
    importLoading,
    loadProducts,
    handleImport,
    handleDeleteAll,
  };
}
