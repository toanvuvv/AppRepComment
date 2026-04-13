import apiClient from "./client";

export interface NickLive {
  id: number;
  name: string;
  user_id: number;
  shop_id: number | null;
  avatar: string | null;
  created_at: string;
}

export interface LiveSession {
  sessionId: number;
  title: string;
  coverImage: string;
  startTime: number;
  duration: number;
  status: number;
  views: number;
  viewers: number;
  peakViewers: number;
  comments: number;
}

export interface LiveSessionsResponse {
  sessions: LiveSession[];
  active_session: LiveSession | null;
}

export interface ScanStatus {
  is_scanning: boolean;
  session_id: number | null;
  comment_count: number;
}

export interface CommentItem {
  id?: string;
  userName?: string;
  username?: string;
  nick_name?: string;
  nickname?: string;
  content?: string;
  comment?: string;
  message?: string;
  msg?: string;
  timestamp?: number;
  create_time?: number;
  ctime?: number;
  streamerId?: number;
  userId?: number;
  user_id?: number;
  uid?: number;
}

export async function createNickLive(data: {
  user: Record<string, unknown>;
  cookies: string;
}): Promise<NickLive> {
  const res = await apiClient.post("/nick-lives", data);
  return res.data;
}

export async function listNickLives(): Promise<NickLive[]> {
  const res = await apiClient.get("/nick-lives");
  return res.data;
}

export async function deleteNickLive(id: number): Promise<void> {
  await apiClient.delete(`/nick-lives/${id}`);
}

export async function getSessions(
  id: number
): Promise<LiveSessionsResponse> {
  const res = await apiClient.get(`/nick-lives/${id}/sessions`);
  return res.data;
}

export async function startScan(
  id: number,
  sessionId: number
): Promise<void> {
  await apiClient.post(
    `/nick-lives/${id}/scan/start?session_id=${sessionId}`
  );
}

export async function stopScan(id: number): Promise<void> {
  await apiClient.post(`/nick-lives/${id}/scan/stop`);
}

export async function getScanStatus(id: number): Promise<ScanStatus> {
  const res = await apiClient.get(`/nick-lives/${id}/scan/status`);
  return res.data;
}

export async function getComments(id: number): Promise<CommentItem[]> {
  const res = await apiClient.get(`/nick-lives/${id}/comments`);
  return res.data;
}

// --- Moderator API ---

export interface ModeratorStatus {
  nick_live_id: number;
  configured: boolean;
  host_id: string | null;
  has_usersig: boolean;
}

export interface ModeratorReplyResult {
  success: boolean;
  status_code?: number;
  response?: string;
  guest?: string;
  reply?: string;
  error?: string;
}

export async function saveModeratorCurl(
  nickLiveId: number,
  curlText: string
): Promise<{ nick_live_id: number; host_id: string; status: string }> {
  const res = await apiClient.post(
    `/nick-lives/${nickLiveId}/moderator/save-curl`,
    { curl_text: curlText }
  );
  return res.data;
}

export async function getModeratorStatus(
  nickLiveId: number
): Promise<ModeratorStatus> {
  const res = await apiClient.get(
    `/nick-lives/${nickLiveId}/moderator/status`
  );
  return res.data;
}

export async function removeModerator(nickLiveId: number): Promise<void> {
  await apiClient.delete(`/nick-lives/${nickLiveId}/moderator`);
}

export async function sendModeratorReply(
  nickLiveId: number,
  guestName: string,
  guestId: number,
  replyText: string
): Promise<ModeratorReplyResult> {
  const payload = {
    guest_name: guestName,
    guest_id: guestId,
    reply_text: replyText,
  };
  console.log("[sendModeratorReply] payload →", payload);
  const res = await apiClient.post(
    `/nick-lives/${nickLiveId}/moderator/reply`,
    payload
  );
  console.log("[sendModeratorReply] response →", res.data);
  return res.data;
}

export async function autoReplyComments(
  nickLiveId: number,
  comments: CommentItem[],
  replyText: string
): Promise<ModeratorReplyResult[]> {
  const res = await apiClient.post(
    `/nick-lives/${nickLiveId}/moderator/auto-reply`,
    {
      comments,
      reply_text: replyText,
    }
  );
  return res.data;
}
