import type {
  AdminStats,
  FileInfo,
  Job,
  JobList,
  LoginResponse,
  ToolInfo,
  User,
} from "./types";

const BASE = "/api/v1";
const TOKEN_KEY = "selfx_token";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

function handleUnauthorized(): void {
  clearToken();
  if (window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
}

async function errorDetail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (body.detail !== undefined) return JSON.stringify(body.detail);
  } catch {
    // Non-JSON error body; fall through to generic message.
  }
  return `Request failed (HTTP ${res.status})`;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  auth = true,
): Promise<T> {
  const headers = new Headers(init.headers);
  if (auth) {
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Network error: could not reach the server");
  }
  if (res.status === 401 && auth) {
    const detail = await errorDetail(res);
    handleUnauthorized();
    throw new ApiError(401, detail);
  }
  if (!res.ok) {
    throw new ApiError(res.status, await errorDetail(res));
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

// --- health ---

export function healthz(): Promise<{ status: string }> {
  return request<{ status: string }>("/healthz", {}, false);
}

// --- auth ---

export function login(
  username: string,
  password: string,
): Promise<LoginResponse> {
  return request<LoginResponse>(
    "/auth/login",
    jsonInit("POST", { username, password }),
    false,
  );
}

export function me(): Promise<User> {
  return request<User>("/auth/me");
}

// --- tools ---

export function listTools(): Promise<ToolInfo[]> {
  return request<ToolInfo[]>("/tools");
}

// --- files ---

export function uploadFile(file: File): Promise<FileInfo> {
  const form = new FormData();
  form.append("file", file);
  return request<FileInfo>("/files", { method: "POST", body: form });
}

/** Fetches a file with the auth header and triggers a browser download. */
export async function downloadFile(file: {
  id: string;
  orig_name: string;
}): Promise<void> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res: Response;
  try {
    res = await fetch(`${BASE}/files/${file.id}/download`, { headers });
  } catch {
    throw new ApiError(0, "Network error: could not reach the server");
  }
  if (res.status === 401) {
    handleUnauthorized();
    throw new ApiError(401, "Session expired");
  }
  if (!res.ok) {
    throw new ApiError(res.status, await errorDetail(res));
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = file.orig_name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// --- jobs ---

export function createJob(
  tool: string,
  fileIds: string[],
  params: Record<string, unknown>,
): Promise<Job> {
  return request<Job>(
    "/jobs",
    jsonInit("POST", { tool, file_ids: fileIds, params }),
  );
}

export function listJobs(limit = 50, offset = 0): Promise<JobList> {
  return request<JobList>(`/jobs?limit=${limit}&offset=${offset}`);
}

export function getJob(id: string): Promise<Job> {
  return request<Job>(`/jobs/${id}`);
}

export function cancelJob(id: string): Promise<Job> {
  return request<Job>(`/jobs/${id}/cancel`, { method: "POST" });
}

export function deleteJob(id: string): Promise<void> {
  return request<void>(`/jobs/${id}`, { method: "DELETE" });
}

// --- admin ---

export function adminStats(): Promise<AdminStats> {
  return request<AdminStats>("/admin/stats");
}

export function adminListUsers(): Promise<User[]> {
  return request<User[]>("/admin/users");
}

export function adminCreateUser(
  username: string,
  password: string,
  isAdmin: boolean,
): Promise<User> {
  return request<User>(
    "/admin/users",
    jsonInit("POST", { username, password, is_admin: isAdmin }),
  );
}

export function adminUpdateUser(
  id: string,
  patch: { password?: string; is_admin?: boolean; disabled?: boolean },
): Promise<User> {
  return request<User>(`/admin/users/${id}`, jsonInit("PATCH", patch));
}

export function adminDeleteUser(id: string): Promise<void> {
  return request<void>(`/admin/users/${id}`, { method: "DELETE" });
}

export function adminListJobs(limit = 50, offset = 0): Promise<JobList> {
  return request<JobList>(`/admin/jobs?limit=${limit}&offset=${offset}`);
}

// --- knowledge base ---

export interface KbCollection {
  id: string;
  name: string;
  embed_model: string;
  allow_cloud: boolean;
  documents: number;
  chunks: number;
}
export interface KbDocument {
  id: string;
  orig_name: string;
  status: string;
  n_chunks: number;
  error: string | null;
}
export interface Citation {
  n: number;
  document: string;
  ordinal: number;
  snippet: string;
}
export interface KbChatResponse {
  answer: string;
  citations: Citation[];
  sources: string[];
}
export interface KbMessage {
  role: string;
  content: string;
  citations: Citation[];
}

export function kbListCollections(): Promise<KbCollection[]> {
  return request<KbCollection[]>("/kb/collections");
}
export function kbCreateCollection(name: string): Promise<KbCollection> {
  return request<KbCollection>("/kb/collections", jsonInit("POST", { name }));
}
export function kbDeleteCollection(id: string): Promise<void> {
  return request<void>(`/kb/collections/${id}`, { method: "DELETE" });
}
export function kbListDocuments(id: string): Promise<KbDocument[]> {
  return request<KbDocument[]>(`/kb/collections/${id}/documents`);
}
export function kbAddDocuments(id: string, fileIds: string[]): Promise<KbDocument[]> {
  return request<KbDocument[]>(`/kb/collections/${id}/documents`, jsonInit("POST", { file_ids: fileIds }));
}
export function kbChat(id: string, question: string): Promise<KbChatResponse> {
  return request<KbChatResponse>(`/kb/collections/${id}/chat`, jsonInit("POST", { question }));
}
export function kbMessages(id: string): Promise<KbMessage[]> {
  return request<KbMessage[]>(`/kb/collections/${id}/messages`);
}

// --- agent ---

export interface AgentStep {
  tool: string;
  args: Record<string, unknown>;
  result: {
    ok?: boolean;
    status?: string;
    error?: string;
    outputs?: { id: string; name: string; size: number }[];
  } & Record<string, unknown>;
}
export interface AgentReply {
  answer: string;
  steps: AgentStep[];
  provider: string;
}
export interface AgentStatus {
  default_provider: string;
  gemini_available: boolean;
  local_model: string;
  gemini_model: string;
}
export function agentStatus(): Promise<AgentStatus> {
  return request<AgentStatus>("/agent/status");
}
export function agentChat(message: string, fileIds: string[], provider?: string): Promise<AgentReply> {
  return request<AgentReply>("/agent/chat", jsonInit("POST", { message, file_ids: fileIds, provider }));
}
