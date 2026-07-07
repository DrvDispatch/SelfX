// Shapes mirror docs/SPEC.md §5 exactly.

export interface User {
  id: string;
  username: string;
  is_admin: boolean;
  // Present on admin endpoints; optional so the login payload still conforms.
  disabled?: boolean;
  created_at?: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  user: User;
}

// JSON Schema (draft 7 subset) used for tool params, per SPEC §7.
export interface ParamProperty {
  type?: "string" | "number" | "integer" | "boolean";
  title?: string;
  description?: string;
  default?: unknown;
  enum?: Array<string | number>;
  minimum?: number;
  maximum?: number;
  format?: string;
}

export interface ParamsSchema {
  type?: string;
  properties?: Record<string, ParamProperty>;
  required?: string[];
}

export interface ToolInfo {
  slug: string;
  name: string;
  category: string;
  description: string;
  accepts: string[];
  multi_file: boolean;
  min_files: number;
  params_schema: ParamsSchema;
  queue: "default" | "heavy";
  available: boolean;
  unavailable_reason: string | null;
}

export interface FileInfo {
  id: string;
  orig_name: string;
  size: number;
  mime: string;
  created_at: string;
  expires_at: string | null;
}

export type JobStatus = "queued" | "running" | "done" | "error" | "canceled";

export interface Job {
  id: string;
  tool: string;
  status: JobStatus;
  progress: number;
  message: string | null;
  params: Record<string, unknown>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  input_files: FileInfo[];
  output_files: FileInfo[];
}

export interface JobList {
  items: Job[];
  total: number;
}

export interface AdminStats {
  users: number;
  jobs_total: number;
  jobs_by_status: Record<string, number>;
  disk_used_bytes: number;
  queue_depth: {
    default: number;
    heavy: number;
  };
}
