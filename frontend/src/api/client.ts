import axios, { type InternalAxiosRequestConfig } from "axios";
import { getViewAsUserId } from "../stores/viewAsStore";

const apiClient = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

// Routes that participate in the cross-user (as_user_id) context.
// Keep this list in sync with backend routers using resolve_user_context.
const CROSS_USER_PREFIXES = [
  "/nick-lives",
  "/reply-logs",
  "/settings",
];

function shouldAttachAsUserId(url: string | undefined): boolean {
  if (!url) return false;
  const path = url.startsWith("/") ? url : `/${url}`;
  return CROSS_USER_PREFIXES.some((p) => path === p || path.startsWith(`${p}/`) || path.startsWith(`${p}?`));
}

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const raw = localStorage.getItem("auth");
  if (raw) {
    try {
      const { token } = JSON.parse(raw);
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    } catch {
      /* ignore */
    }
  }

  const asUserId = getViewAsUserId();
  if (asUserId !== null && shouldAttachAsUserId(config.url)) {
    config.params = { ...(config.params ?? {}), as_user_id: asUserId };
  }

  return config;
});

apiClient.interceptors.response.use(
  (r) => r,
  (error) => {
    const status = error.response?.status;
    const url = error.config?.url ?? "";
    if ((status === 401 || status === 403) && !url.includes("/auth/login")) {
      localStorage.removeItem("auth");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  },
);

/** Append `token` query param to a URL (for SSE / static <a> links). */
export function withTokenQuery(url: string): string {
  const raw = localStorage.getItem("auth");
  if (!raw) return url;
  try {
    const { token } = JSON.parse(raw);
    if (!token) return url;
    const sep = url.includes("?") ? "&" : "?";
    return `${url}${sep}token=${encodeURIComponent(token)}`;
  } catch {
    return url;
  }
}

/** Append both `token` and (if active) `as_user_id` query params. Use for SSE. */
export function withAuthQuery(url: string): string {
  let out = withTokenQuery(url);
  const asUserId = getViewAsUserId();
  if (asUserId !== null) {
    const sep = out.includes("?") ? "&" : "?";
    out = `${out}${sep}as_user_id=${asUserId}`;
  }
  return out;
}

export default apiClient;
