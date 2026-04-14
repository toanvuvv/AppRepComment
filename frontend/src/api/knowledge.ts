import apiClient from "./client";

export interface KnowledgeProduct {
  pk: number;
  product_order: number;
  nick_live_id: number;
  item_id: number;
  shop_id: number;
  name: string;
  keywords: string;
  price_min: number | null;
  price_max: number | null;
  discount_pct: number | null;
  in_stock: boolean;
  stock_qty: number | null;
  sold: number | null;
  rating: number | null;
  rating_count: number | null;
  voucher_info: string | null;
  promotion_info: string | null;
}

export async function importKnowledgeProducts(
  nickLiveId: number,
  rawJson: string
): Promise<KnowledgeProduct[]> {
  const res = await apiClient.post(
    `/nick-lives/${nickLiveId}/knowledge/import`,
    { raw_json: rawJson }
  );
  return res.data;
}

export async function getKnowledgeProducts(
  nickLiveId: number
): Promise<KnowledgeProduct[]> {
  const res = await apiClient.get(
    `/nick-lives/${nickLiveId}/knowledge/products`
  );
  return res.data;
}

export async function deleteKnowledgeProducts(
  nickLiveId: number
): Promise<void> {
  await apiClient.delete(`/nick-lives/${nickLiveId}/knowledge/products`);
}

// --- Knowledge AI Config ---

export interface KnowledgeAIConfig {
  system_prompt: string;
  model: string;
}

export async function getKnowledgeAIConfig(): Promise<KnowledgeAIConfig> {
  const res = await apiClient.get("/settings/knowledge-ai");
  return res.data;
}

export async function updateKnowledgeAIConfig(
  data: Partial<{ system_prompt: string; model: string }>
): Promise<void> {
  await apiClient.put("/settings/knowledge-ai", data);
}

// --- Banned Words ---

export interface BannedWords {
  words: string[];
}

export async function getBannedWords(): Promise<BannedWords> {
  const res = await apiClient.get("/settings/banned-words");
  return res.data;
}

export async function updateBannedWords(words: string[]): Promise<void> {
  await apiClient.put("/settings/banned-words", { words });
}
