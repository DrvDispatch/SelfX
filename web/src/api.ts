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

/**
 * Upload a file with progress callbacks (fraction 0..1). Uses XHR so we can
 * observe upload.onprogress, which fetch() can't do. Returns the same FileInfo.
 */
export function uploadFileWithProgress(
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<FileInfo> {
  return new Promise<FileInfo>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/files`);
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded / e.total);
      };
    }
    xhr.onload = () => {
      if (xhr.status === 401) {
        handleUnauthorized();
        reject(new ApiError(401, "Session expired"));
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as FileInfo);
        } catch {
          reject(new ApiError(xhr.status, "Unexpected server response"));
        }
      } else {
        let detail = `Upload failed (HTTP ${xhr.status})`;
        try {
          const body = JSON.parse(xhr.responseText) as { detail?: unknown };
          if (typeof body.detail === "string") detail = body.detail;
        } catch {
          // non-JSON error body
        }
        reject(new ApiError(xhr.status, detail));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "Network error during upload"));
    xhr.onabort = () => reject(new ApiError(0, "Upload cancelled"));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

/** Fetches a file's bytes with the auth header (for inline previews). */
export async function fetchFileBlob(id: string): Promise<Blob> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${BASE}/files/${id}/download`, { headers });
  if (res.status === 401) {
    handleUnauthorized();
    throw new ApiError(401, "Session expired");
  }
  if (!res.ok) throw new ApiError(res.status, await errorDetail(res));
  return res.blob();
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

/** Run one single-file tool over many files; outputs come back as one zip. */
export function createBatchJob(
  tool: string,
  fileIds: string[],
  params: Record<string, unknown>,
): Promise<Job> {
  return request<Job>(
    "/jobs/batch",
    jsonInit("POST", { tool, file_ids: fileIds, params }),
  );
}

export interface PipelineStep {
  tool: string;
  params: Record<string, unknown>;
}

/** Run a linear chain of single-file tools; each step's output feeds the next. */
export function createPipelineJob(
  steps: PipelineStep[],
  fileIds: string[],
): Promise<Job> {
  return request<Job>(
    "/jobs/pipeline",
    jsonInit("POST", { steps, file_ids: fileIds }),
  );
}

export function listJobs(limit = 50, offset = 0): Promise<JobList> {
  return request<JobList>(`/jobs?limit=${limit}&offset=${offset}`);
}

export interface JobEvent {
  id: string;
  tool: string;
  status: string;
  progress: number;
  message: string | null;
}

/**
 * Subscribe to live job updates over SSE (fetch-based so we can send the auth
 * header). Auto-reconnects on drop. Returns a stop() function.
 */
export function streamJobEvents(onEvent: (e: JobEvent) => void): () => void {
  const controller = new AbortController();
  let stopped = false;

  const run = async () => {
    while (!stopped) {
      try {
        const token = getToken();
        const res = await fetch(`${BASE}/jobs/stream`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: controller.signal,
        });
        if (res.status === 401) {
          handleUnauthorized();
          return;
        }
        if (!res.ok || !res.body) throw new Error("stream failed");
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buf.indexOf("\n\n")) !== -1) {
            const block = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            for (const line of block.split("\n")) {
              if (line.startsWith("data:")) {
                const payload = line.slice(5).trim();
                if (payload) {
                  try {
                    onEvent(JSON.parse(payload) as JobEvent);
                  } catch {
                    /* ignore malformed event */
                  }
                }
              }
            }
          }
        }
      } catch {
        if (stopped || controller.signal.aborted) return;
      }
      if (stopped) return;
      await new Promise((r) => setTimeout(r, 2000)); // reconnect backoff
    }
  };

  void run();
  return () => {
    stopped = true;
    controller.abort();
  };
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

// --- presets ---

export interface Preset {
  id: string;
  name: string;
  tool: string;
  params: Record<string, unknown>;
  created_at: string;
}

export function listPresets(): Promise<Preset[]> {
  return request<Preset[]>("/presets");
}

export function createPreset(
  name: string,
  tool: string,
  params: Record<string, unknown>,
): Promise<Preset> {
  return request<Preset>("/presets", jsonInit("POST", { name, tool, params }));
}

export function deletePreset(id: string): Promise<void> {
  return request<void>(`/presets/${id}`, { method: "DELETE" });
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

// --- ollama model management (admin) ---

export interface OllamaModel {
  name: string;
  size: number;
  details?: { parameter_size?: string; quantization_level?: string };
}
export function listModels(): Promise<{ models: OllamaModel[]; pulling: string[] }> {
  return request<{ models: OllamaModel[]; pulling: string[] }>("/admin/models");
}
export function pullModel(name: string): Promise<{ status: string; name: string }> {
  return request<{ status: string; name: string }>("/admin/models/pull", jsonInit("POST", { name }));
}
export function deleteModel(name: string): Promise<{ deleted: string }> {
  return request<{ deleted: string }>(`/admin/models/${encodeURIComponent(name)}`, { method: "DELETE" });
}
