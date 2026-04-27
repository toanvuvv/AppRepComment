import apiClient from "./client";

export type ProxyScheme = "socks5" | "http" | "https";

export interface SeedingProxy {
  id: number;
  scheme: ProxyScheme;
  host: string;
  port: number;
  username: string | null;
  note: string | null;
  created_at: string;
  used_by_count: number;
}

export interface ProxyCreatePayload {
  scheme: ProxyScheme;
  host: string;
  port: number;
  username?: string | null;
  password?: string | null;
  note?: string | null;
}

export type ProxyUpdatePatch = Partial<ProxyCreatePayload>;

export interface ProxyImportPayload {
  scheme: ProxyScheme;
  raw_text: string;
}

export interface ProxyImportError {
  line: number;
  raw: string;
  reason: string;
}

export interface ProxyImportResult {
  created: number;
  skipped_duplicates: number;
  errors: ProxyImportError[];
}

export interface ProxyAssignPayload {
  only_unassigned: boolean;
}

export interface ProxyAssignResult {
  assigned: number;
  reason: "ok" | "no_proxies" | "no_clones" | "all_assigned";
}

export interface RequireProxySetting {
  require_proxy: boolean;
}

export async function listProxies(): Promise<SeedingProxy[]> {
  const res = await apiClient.get("/seeding/proxies");
  return res.data;
}

export async function createProxy(
  payload: ProxyCreatePayload,
): Promise<SeedingProxy> {
  const res = await apiClient.post("/seeding/proxies", payload);
  return res.data;
}

export async function updateProxy(
  id: number,
  patch: ProxyUpdatePatch,
): Promise<SeedingProxy> {
  const res = await apiClient.patch(`/seeding/proxies/${id}`, patch);
  return res.data;
}

export async function deleteProxy(id: number): Promise<void> {
  await apiClient.delete(`/seeding/proxies/${id}`);
}

export async function importProxies(
  payload: ProxyImportPayload,
): Promise<ProxyImportResult> {
  const res = await apiClient.post("/seeding/proxies/import", payload);
  return res.data;
}

export async function assignProxies(
  payload: ProxyAssignPayload,
): Promise<ProxyAssignResult> {
  const res = await apiClient.post("/seeding/proxies/assign", payload);
  return res.data;
}

export async function getProxySetting(): Promise<RequireProxySetting> {
  const res = await apiClient.get("/seeding/proxies/setting");
  return res.data;
}

export async function setProxySetting(
  payload: RequireProxySetting,
): Promise<RequireProxySetting> {
  const res = await apiClient.put("/seeding/proxies/setting", payload);
  return res.data;
}
