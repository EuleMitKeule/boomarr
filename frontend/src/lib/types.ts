export type Json = unknown;
export type ConfigData = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export interface AuthState {
  method: "forms" | "external" | "none";
  setup_required: boolean;
  setup_token_required: boolean;
  password_login: boolean;
  oidc: { enabled: boolean; name: string; auto_login: boolean };
  user: { name: string; method: string } | null;
}

export interface ScanResult {
  created: number;
  removed: number;
  unchanged: number;
  probed: number;
  skipped: number;
  filtered: number;
  errors: number;
  blocked: number;
  links: Record<string, number>;
  changed_outputs: string[];
  changes?: ScanChange[];
  changes_count?: number;
}

export interface ScanChange {
  action: "created" | "removed";
  path: string;
  target?: string | null;
}

export interface ScanRecord {
  id?: number;
  started_at: number;
  finished_at: number;
  duration_seconds: number;
  error: string | null;
  dry_run: boolean;
  force: boolean;
  source: string;
  cancelled: boolean;
  result?: ScanResult;
}

export interface Progress {
  library: string;
  phase: "discovering" | "probing" | "linking";
  done: number;
  total: number;
}

export interface OutputStatus {
  path: string;
  exists: boolean;
  links: number;
  filters: string[];
}

export interface LibraryStatus {
  name: string;
  input_path: string;
  input_available: boolean;
  outputs: OutputStatus[];
}

export interface Dashboard {
  version: string;
  started_at: number;
  scanning: boolean;
  scan_started_at: number | null;
  current_scan: { source: string; dry_run: boolean; force: boolean } | null;
  progress: Progress | null;
  queued: number;
  next_scheduled_scan: number | null;
  restart_required: boolean;
  last_scan: ScanRecord | null;
  cache: {
    total_cached: number;
    without_audio: number;
    last_probe_time: number | null;
    languages: Record<string, number>;
  };
  triggers: string[];
  libraries: LibraryStatus[];
}

export interface HealthCheck {
  id: string;
  level: "ok" | "warning" | "error";
  message: string;
  wiki: string | null;
}

export interface SystemStatus {
  version: string;
  python: string;
  platform: string;
  pid: number;
  started_at: number;
  uptime_seconds: number;
  config_file: string;
  config_writable: boolean;
  database: string;
  log_file: string | null;
  auth_method: string;
  restart_required: boolean;
  user: { name: string; method: string };
  in_container: boolean;
}

export interface ConfigDocument {
  config: ConfigData;
  etag: string;
  writable: boolean;
  path: string;
  env_overrides: string[];
  warnings: string[];
  restart_required?: boolean;
}

export interface LogEntry {
  id: number;
  time: number;
  level: string;
  logger: string;
  message: string;
}

export interface Language {
  code: string;
  name: string;
  code1: string;
}

export interface LiveEvent<T = unknown> {
  id: number;
  type: string;
  time: number;
  data: T;
}
