// frontend/src/api/hostConfig.ts
import apiClient from "./client";

// --- Interfaces ---

export interface HostConfigStatus {
  configured: boolean;
  uuid: string | null;
  has_usersig: boolean;
  proxy: string | null;
}

export interface AutoPostTemplate {
  id: number;
  content: string;
  min_interval_seconds: number;
  max_interval_seconds: number;
  nick_live_id: number;
}

export interface ReplyTemplate {
  id: number;
  content: string;
  nick_live_id: number;
}

export type ReplyMode = "none" | "knowledge" | "ai" | "template";

export interface NickLiveSettings {
  nick_live_id: number;
  reply_mode: ReplyMode;
  reply_to_host: boolean;
  reply_to_moderator: boolean;
  auto_post_enabled: boolean;
  auto_post_to_host: boolean;
  auto_post_to_moderator: boolean;
  auto_pin_enabled: boolean;
  pin_min_interval_minutes: number;
  pin_max_interval_minutes: number;
}

export interface NickLiveSettingsUpdate {
  reply_mode?: ReplyMode;
  reply_to_host?: boolean;
  reply_to_moderator?: boolean;
  auto_post_enabled?: boolean;
  auto_post_to_host?: boolean;
  auto_post_to_moderator?: boolean;
  host_proxy?: string;
  auto_pin_enabled?: boolean;
  pin_min_interval_minutes?: number;
  pin_max_interval_minutes?: number;
}

// --- Host credentials ---

export async function getHostStatus(nickLiveId: number): Promise<HostConfigStatus> {
  const res = await apiClient.get(`/nick-lives/${nickLiveId}/host/status`);
  return res.data;
}

export async function getHostCredentials(nickLiveId: number): Promise<HostConfigStatus> {
  try {
    const res = await apiClient.post(`/nick-lives/${nickLiveId}/host/get-credentials`);
    // DEBUG_RELIVE: log outgoing payload + raw relive response
    if (res.data?.debug) {
      // // eslint-disable-next-line no-console
      // console.groupCollapsed("[DEBUG_RELIVE] get-credentials OK");
      // // eslint-disable-next-line no-console
      // console.log("payload →", res.data.debug.payload);
      // // eslint-disable-next-line no-console
      // console.log("cookies →", res.data.debug.cookies);
      // // eslint-disable-next-line no-console
      // console.log("status ←", res.data.debug.status_code);
      // // eslint-disable-next-line no-console
      // console.log("response_text ←", res.data.debug.response_text);
      // // eslint-disable-next-line no-console
      // console.groupEnd();
    }
    return res.data;
  } catch (err: unknown) {
    // DEBUG_RELIVE: log debug info from error response
    const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
    if (detail && typeof detail === "object") {
      // // eslint-disable-next-line no-console
      // console.groupCollapsed("[DEBUG_RELIVE] get-credentials FAILED");
      // // eslint-disable-next-line no-console
      // console.log("detail →", detail);
      // // eslint-disable-next-line no-console
      // console.groupEnd();
    }
    throw err;
  }
}

export async function hostPostComment(
  nickLiveId: number,
  content: string,
  sessionId: string
): Promise<void> {
  await apiClient.post(`/nick-lives/${nickLiveId}/host/post`, { content, session_id: sessionId });
}

// --- Auto-post templates ---

export async function getAutoPostTemplates(nickLiveId: number): Promise<AutoPostTemplate[]> {
  const res = await apiClient.get(`/nick-lives/${nickLiveId}/auto-post-templates`);
  return res.data;
}

export async function createAutoPostTemplate(
  nickLiveId: number,
  content: string,
  min_interval_seconds: number,
  max_interval_seconds: number
): Promise<AutoPostTemplate> {
  const res = await apiClient.post(`/nick-lives/${nickLiveId}/auto-post-templates`, {
    content,
    min_interval_seconds,
    max_interval_seconds,
  });
  return res.data;
}

export async function updateAutoPostTemplate(
  nickLiveId: number,
  templateId: number,
  updates: Partial<{ content: string; min_interval_seconds: number; max_interval_seconds: number }>
): Promise<AutoPostTemplate> {
  const res = await apiClient.put(
    `/nick-lives/${nickLiveId}/auto-post-templates/${templateId}`,
    updates
  );
  return res.data;
}

export async function deleteAutoPostTemplate(
  nickLiveId: number,
  templateId: number
): Promise<void> {
  await apiClient.delete(`/nick-lives/${nickLiveId}/auto-post-templates/${templateId}`);
}

// --- Auto-post control ---

export async function startAutoPost(
  nickLiveId: number,
  sessionId: string
): Promise<void> {
  await apiClient.post(`/nick-lives/${nickLiveId}/auto-post/start`, { session_id: sessionId });
}

export async function stopAutoPost(nickLiveId: number): Promise<void> {
  await apiClient.post(`/nick-lives/${nickLiveId}/auto-post/stop`);
}

export async function getAutoPostStatus(
  nickLiveId: number
): Promise<{ running: boolean; session_id: string | null }> {
  const res = await apiClient.get(`/nick-lives/${nickLiveId}/auto-post/status`);
  return res.data;
}

// --- Auto-pin control ---

export async function startAutoPin(
  nickLiveId: number,
  sessionId: string
): Promise<void> {
  await apiClient.post(`/nick-lives/${nickLiveId}/auto-pin/start`, { session_id: sessionId });
}

export async function stopAutoPin(nickLiveId: number): Promise<void> {
  await apiClient.post(`/nick-lives/${nickLiveId}/auto-pin/stop`);
}

export async function getAutoPinStatus(
  nickLiveId: number
): Promise<{ running: boolean }> {
  const res = await apiClient.get(`/nick-lives/${nickLiveId}/auto-pin/status`);
  return res.data;
}

// --- Per-nick reply templates ---

export async function getReplyTemplates(nickLiveId: number): Promise<ReplyTemplate[]> {
  const res = await apiClient.get(`/nick-lives/${nickLiveId}/reply-templates`);
  return res.data;
}

export async function createReplyTemplate(
  nickLiveId: number,
  content: string
): Promise<ReplyTemplate> {
  const res = await apiClient.post(`/nick-lives/${nickLiveId}/reply-templates`, { content });
  return res.data;
}

export async function deleteReplyTemplate(
  nickLiveId: number,
  templateId: number
): Promise<void> {
  await apiClient.delete(`/nick-lives/${nickLiveId}/reply-templates/${templateId}`);
}

// --- Nick settings ---

export async function getNickSettings(nickLiveId: number): Promise<NickLiveSettings> {
  const res = await apiClient.get(`/nick-lives/${nickLiveId}/settings`);
  return res.data;
}

export async function updateNickSettings(
  nickLiveId: number,
  updates: NickLiveSettingsUpdate
): Promise<NickLiveSettings> {
  const res = await apiClient.put(`/nick-lives/${nickLiveId}/settings`, updates);
  return res.data;
}
