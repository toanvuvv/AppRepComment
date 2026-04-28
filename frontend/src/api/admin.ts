import apiClient from "./client";

export type AiKeyMode = "own" | "system";

export interface AdminUser {
  id: number;
  username: string;
  role: "admin" | "user";
  max_nicks: number | null;
  is_locked: boolean;
  created_at: string;
  nick_count: number;
  clone_count: number;
  live_reply_enabled_count: number;
  ai_key_mode: AiKeyMode;
  openai_own_key_set: boolean;
}

export interface AdminUserNick {
  id: number;
  name: string;
  shopee_user_id: number;
  reply_mode: "none" | "knowledge" | "ai" | "template";
  reply_enabled: boolean;
  reply_to_host: boolean;
  reply_to_moderator: boolean;
  auto_post_enabled: boolean;
  auto_pin_enabled: boolean;
}

export async function listUsers(): Promise<AdminUser[]> {
  const { data } = await apiClient.get<AdminUser[]>("/admin/users");
  return data;
}

export async function listUserNicks(userId: number): Promise<AdminUserNick[]> {
  const { data } = await apiClient.get<AdminUserNick[]>(
    `/admin/users/${userId}/nicks`
  );
  return data;
}

export async function createUser(body: {
  username: string;
  password: string;
  max_nicks: number | null;
  ai_key_mode?: AiKeyMode;
}): Promise<AdminUser> {
  const { data } = await apiClient.post<AdminUser>("/admin/users", body);
  return data;
}

export async function updateUser(
  id: number,
  body: {
    max_nicks?: number | null;
    is_locked?: boolean;
    new_password?: string;
    ai_key_mode?: AiKeyMode;
  }
): Promise<AdminUser> {
  const { data } = await apiClient.patch<AdminUser>(`/admin/users/${id}`, body);
  return data;
}

export async function deleteUser(id: number): Promise<void> {
  await apiClient.delete(`/admin/users/${id}`);
}

// --- System keys (admin only) ---

export interface SystemKeysStatus {
  relive_api_key_set: boolean;
  openai_api_key_set: boolean;
  openai_model: string | null;
}

export async function getSystemKeys(): Promise<SystemKeysStatus> {
  const { data } = await apiClient.get<SystemKeysStatus>("/admin/system-keys");
  return data;
}

export async function updateSystemRelive(api_key: string): Promise<void> {
  await apiClient.put("/admin/system-keys/relive", { api_key });
}

export async function updateSystemOpenAI(
  api_key: string,
  model: string
): Promise<void> {
  await apiClient.put("/admin/system-keys/openai", { api_key, model });
}
