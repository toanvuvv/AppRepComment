// frontend/src/api/settings.ts
import apiClient from "./client";

export interface OpenAIConfig {
  api_key_set: boolean;
  model: string | null;
}

export interface SystemPrompt {
  prompt: string;
}

export interface ReplyTemplate {
  id: number;
  content: string;
}

export interface AutoPostTemplate {
  id: number;
  content: string;
  min_interval_seconds: number;
  max_interval_seconds: number;
}

export interface NickLiveSettings {
  nick_live_id: number;
  ai_reply_enabled: boolean;
  auto_reply_enabled: boolean;
  auto_post_enabled: boolean;
}

// --- OpenAI ---

export async function getOpenAIConfig(): Promise<OpenAIConfig> {
  const res = await apiClient.get("/settings/openai");
  return res.data;
}

export async function updateOpenAIConfig(api_key: string, model: string): Promise<void> {
  await apiClient.put("/settings/openai", { api_key, model });
}

// --- System prompt ---

export async function getSystemPrompt(): Promise<SystemPrompt> {
  const res = await apiClient.get("/settings/system-prompt");
  return res.data;
}

export async function updateSystemPrompt(prompt: string): Promise<void> {
  await apiClient.put("/settings/system-prompt", { prompt });
}

// --- Reply templates ---

export async function getReplyTemplates(): Promise<ReplyTemplate[]> {
  const res = await apiClient.get("/settings/reply-templates");
  return res.data;
}

export async function createReplyTemplate(content: string): Promise<ReplyTemplate> {
  const res = await apiClient.post("/settings/reply-templates", { content });
  return res.data;
}

export async function deleteReplyTemplate(id: number): Promise<void> {
  await apiClient.delete(`/settings/reply-templates/${id}`);
}

// --- Auto-post templates ---

export async function getAutoPostTemplates(): Promise<AutoPostTemplate[]> {
  const res = await apiClient.get("/settings/auto-post-templates");
  return res.data;
}

export async function createAutoPostTemplate(
  content: string,
  min_interval_seconds: number,
  max_interval_seconds: number
): Promise<AutoPostTemplate> {
  const res = await apiClient.post("/settings/auto-post-templates", {
    content,
    min_interval_seconds,
    max_interval_seconds,
  });
  return res.data;
}

export async function updateAutoPostTemplate(
  id: number,
  data: Partial<{ content: string; min_interval_seconds: number; max_interval_seconds: number }>
): Promise<AutoPostTemplate> {
  const res = await apiClient.put(`/settings/auto-post-templates/${id}`, data);
  return res.data;
}

export async function deleteAutoPostTemplate(id: number): Promise<void> {
  await apiClient.delete(`/settings/auto-post-templates/${id}`);
}

// --- Nick live settings ---

export async function getNickLiveSettings(nickLiveId: number): Promise<NickLiveSettings> {
  const res = await apiClient.get(`/nick-lives/${nickLiveId}/settings`);
  return res.data;
}

export async function updateNickLiveSettings(
  nickLiveId: number,
  data: Partial<{ ai_reply_enabled: boolean; auto_reply_enabled: boolean; auto_post_enabled: boolean }>
): Promise<NickLiveSettings> {
  const res = await apiClient.put(`/nick-lives/${nickLiveId}/settings`, data);
  return res.data;
}
