/** Thin fetch wrapper for the Boomarr REST API. */

export interface FieldError {
  loc: (string | number)[];
  msg: string;
}

export class ApiError extends Error {
  status: number;
  errors: FieldError[];

  constructor(status: number, message: string, errors: FieldError[] = []) {
    super(message);
    this.status = status;
    this.errors = errors;
  }
}

type Json = Record<string, unknown> | unknown[];

interface RequestOptions {
  method?: string;
  body?: Json | string;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

let onUnauthorized: (() => void) | null = null;

/** Called whenever the API answers 401 (session expired). */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

function detail(data: unknown, fallback: string): string {
  if (data && typeof data === "object" && "detail" in data) {
    const value = (data as { detail: unknown }).detail;
    if (typeof value === "string") return value;
  }
  return fallback;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "X-Requested-With": "boomarr",
    ...options.headers,
  };
  let body: BodyInit | undefined;
  if (typeof options.body === "string") {
    body = options.body;
  } else if (options.body !== undefined) {
    body = JSON.stringify(options.body);
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`api/v1/${path}`, {
    method: options.method ?? "GET",
    headers,
    body,
    credentials: "same-origin",
    signal: options.signal,
  });
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("auth/")) onUnauthorized?.();
    const errors =
      data && typeof data === "object" && Array.isArray((data as { errors?: unknown }).errors)
        ? ((data as { errors: FieldError[] }).errors ?? [])
        : [];
    throw new ApiError(response.status, detail(data, response.statusText || "Request failed"), errors);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body?: Json | string, headers?: Record<string, string>) =>
    request<T>(path, { method: "POST", body, headers }),
  put: <T>(path: string, body: Json, headers?: Record<string, string>) =>
    request<T>(path, { method: "PUT", body, headers }),
};

/** Absolute URL of an API path (for downloads and EventSource). */
export function apiUrl(path: string): string {
  return new URL(`api/v1/${path}`, document.baseURI).toString();
}
