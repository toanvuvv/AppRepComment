import apiClient from "./client";

// ── Types ────────────────────────────────────────────────────────────────────

export interface SeedingClone {
  id: number;
  name: string;
  shopee_user_id: number;
  avatar: string | null;
  proxy: string | null;
  proxy_meta: {
    id: number;
    scheme: "socks5" | "http" | "https";
    host: string;
    port: number;
  } | null;
  last_sent_at: string | null;
  consecutive_failures: number;
  last_status: "success" | "failed" | "rate_limited" | null;
  last_error: string | null;
  auto_disabled: boolean;
  created_at: string;
}

export interface SeedingTemplate {
  id: number;
  content: string;
  enabled: boolean;
  created_at: string;
}

export interface SeedingLogSession {
  id: number;
  user_id: number;
  nick_live_id: number;
  shopee_session_id: number;
  mode: "manual" | "auto";
  started_at: string;
  stopped_at: string | null;
}

export interface SeedingLog {
  id: number;
  seeding_log_session_id: number;
  clone_id: number;
  template_id: number | null;
  content: string;
  status: "success" | "failed" | "rate_limited";
  error: string | null;
  sent_at: string;
}

export interface SeedingRunStatus {
  log_session_id: number;
  running: boolean;
  nick_live_id: number;
  shopee_session_id: number;
  clone_ids: number[];
  min_interval_sec: number;
  max_interval_sec: number;
  started_at: string;
  stopped_at: string | null;
}

export interface ManualSendResult {
  log_id: number;
  status: "success" | "failed";
  error: string | null;
}

// ── Clone API ─────────────────────────────────────────────────────────────────

export interface CreateClonePayload {
  name: string;
  shopee_user_id: number;
  avatar?: string | null;
  proxy?: string | null;
}

export type UpdateClonePatch = Partial<
  Pick<SeedingClone, "name" | "avatar" | "proxy">
>;

export async function listClones(): Promise<SeedingClone[]> {
  const res = await apiClient.get("/seeding/clones");
  return res.data;
}

export async function createClone(
  payload: CreateClonePayload
): Promise<SeedingClone> {
  const res = await apiClient.post("/seeding/clones", payload);
  return res.data;
}

export async function updateClone(
  id: number,
  patch: UpdateClonePatch
): Promise<SeedingClone> {
  const res = await apiClient.patch(`/seeding/clones/${id}`, patch);
  return res.data;
}

export async function deleteClone(id: number): Promise<void> {
  await apiClient.delete(`/seeding/clones/${id}`);
}

export async function reviveClone(id: number): Promise<SeedingClone> {
  const res = await apiClient.post(`/seeding/clones/${id}/revive`);
  return res.data;
}

// ── Template API ──────────────────────────────────────────────────────────────

export type UpdateTemplatePatch = Partial<
  Pick<SeedingTemplate, "content" | "enabled">
>;

export async function listTemplates(): Promise<SeedingTemplate[]> {
  const res = await apiClient.get("/seeding/templates");
  return res.data;
}

export async function createTemplate(
  content: string,
  enabled = true
): Promise<SeedingTemplate> {
  const res = await apiClient.post("/seeding/templates", { content, enabled });
  return res.data;
}

export async function updateTemplate(
  id: number,
  patch: UpdateTemplatePatch
): Promise<SeedingTemplate> {
  const res = await apiClient.patch(`/seeding/templates/${id}`, patch);
  return res.data;
}

export async function deleteTemplate(id: number): Promise<void> {
  await apiClient.delete(`/seeding/templates/${id}`);
}

export async function bulkCreateTemplates(
  lines: string[]
): Promise<SeedingTemplate[]> {
  const res = await apiClient.post("/seeding/templates/bulk", { lines });
  return res.data;
}

// ── Manual Send ───────────────────────────────────────────────────────────────

export interface ManualSendPayload {
  nick_live_id: number;
  shopee_session_id: number;
  clone_id: number;
  content: string;
  template_id?: number | null;
}

export async function manualSend(
  payload: ManualSendPayload
): Promise<ManualSendResult> {
  const res = await apiClient.post("/seeding/manual/send", payload);
  return res.data;
}

// ── Auto Mode ─────────────────────────────────────────────────────────────────

export interface AutoStartPayload {
  nick_live_id: number;
  shopee_session_id: number;
  clone_ids: number[];
  min_interval_sec?: number;
  max_interval_sec?: number;
}

export async function autoStart(
  payload: AutoStartPayload
): Promise<SeedingRunStatus> {
  const res = await apiClient.post("/seeding/auto/start", payload);
  return res.data;
}

export async function autoStop(log_session_id: number): Promise<void> {
  await apiClient.post("/seeding/auto/stop", { log_session_id });
}

export async function autoRunning(): Promise<SeedingRunStatus[]> {
  const res = await apiClient.get("/seeding/auto/running");
  return res.data;
}

export async function autoStatus(
  log_session_id: number
): Promise<SeedingRunStatus> {
  const res = await apiClient.get("/seeding/auto/status", {
    params: { log_session_id },
  });
  return res.data;
}

// ── Log Sessions ──────────────────────────────────────────────────────────────

export interface ListLogSessionsParams {
  nick_live_id?: number;
  mode?: "manual" | "auto";
}

export async function listLogSessions(
  params: ListLogSessionsParams = {}
): Promise<SeedingLogSession[]> {
  const res = await apiClient.get("/seeding/log-sessions", { params });
  return res.data;
}

// ── Logs ──────────────────────────────────────────────────────────────────────

export async function listLogs(
  log_session_id: number,
  page = 1,
  page_size = 50
): Promise<SeedingLog[]> {
  const res = await apiClient.get("/seeding/logs", {
    params: { log_session_id, page, page_size },
  });
  return res.data;
}
