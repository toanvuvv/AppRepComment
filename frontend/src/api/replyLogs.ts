import apiClient from "./client";

export type ReplyOutcome =
  | "success"
  | "failed"
  | "dropped"
  | "circuit_open"
  | "no_config";

export interface ReplyLog {
  id: number;
  nick_live_id: number;
  session_id: number;
  guest_name: string | null;
  guest_id: string | null;
  comment_text: string | null;
  reply_text: string | null;
  reply_type: string | null;
  outcome: ReplyOutcome;
  status_code: number | null;
  error: string | null;
  product_order: number | null;
  latency_ms: number | null;
  llm_latency_ms: number | null;
  retry_count: number;
  cached_hit: boolean;
  created_at: string;
}

export interface ReplyLogStats {
  total: number;
  success: number;
  failed: number;
  dropped: number;
  circuit_open: number;
  no_config: number;
  success_rate: number;
  cache_hit_rate: number;
  avg_latency_ms: number | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  since: string;
  until: string;
}

export interface ListReplyLogsParams {
  nick_live_id?: number;
  outcome?: ReplyOutcome;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
}

export async function listReplyLogs(
  params: ListReplyLogsParams = {}
): Promise<ReplyLog[]> {
  const res = await apiClient.get("/reply-logs", { params });
  return res.data;
}

export async function getReplyLogStats(
  nickLiveId?: number,
  since?: string
): Promise<ReplyLogStats> {
  const params: Record<string, string | number> = {};
  if (nickLiveId !== undefined) params.nick_live_id = nickLiveId;
  if (since) params.since = since;
  const res = await apiClient.get("/reply-logs/stats", { params });
  return res.data;
}
