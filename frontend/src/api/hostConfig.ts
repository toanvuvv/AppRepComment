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
}

export interface NickLiveSettingsUpdate {
  reply_mode?: ReplyMode;
  reply_to_host?: boolean;
  reply_to_moderator?: boolean;
  auto_post_enabled?: boolean;
  auto_post_to_host?: boolean;
  auto_post_to_moderator?: boolean;
  host_proxy?: string;
}

// --- Host credentials ---

export async function getHostStatus(nickLiveId: number): Promise<HostConfigStatus> {
  const res = await apiClient.get(`/nick-lives/${nickLiveId}/host/status`);
  return res.data;
}

export async function getHostCredentials(nickLiveId: number): Promise<HostConfigStatus> {
  const res = await apiClient.post(`/nick-lives/${nickLiveId}/host/get-credentials`);
  return res.data;
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
