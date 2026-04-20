import apiClient from "./client";
import type { AuthUser } from "../contexts/AuthContext";

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const { data } = await apiClient.post<LoginResponse>("/auth/login", { username, password });
  return data;
}

export async function me(): Promise<AuthUser> {
  const { data } = await apiClient.get<AuthUser>("/auth/me");
  return data;
}

export async function changePassword(old_password: string, new_password: string): Promise<void> {
  await apiClient.post("/auth/change-password", { old_password, new_password });
}
