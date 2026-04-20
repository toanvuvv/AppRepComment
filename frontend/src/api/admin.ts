import apiClient from "./client";

export interface AdminUser {
  id: number;
  username: string;
  role: "admin" | "user";
  max_nicks: number | null;
  is_locked: boolean;
  created_at: string;
  nick_count: number;
}

export async function listUsers(): Promise<AdminUser[]> {
  const { data } = await apiClient.get<AdminUser[]>("/admin/users");
  return data;
}

export async function createUser(body: {
  username: string; password: string; max_nicks: number | null;
}): Promise<AdminUser> {
  const { data } = await apiClient.post<AdminUser>("/admin/users", body);
  return data;
}

export async function updateUser(id: number, body: {
  max_nicks?: number | null; is_locked?: boolean; new_password?: string;
}): Promise<AdminUser> {
  const { data } = await apiClient.patch<AdminUser>(`/admin/users/${id}`, body);
  return data;
}

export async function deleteUser(id: number): Promise<void> {
  await apiClient.delete(`/admin/users/${id}`);
}
