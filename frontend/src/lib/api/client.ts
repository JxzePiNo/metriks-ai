import { getApiUrl } from "@/lib/config";
import type { ApiErrorBody } from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * Typed JSON fetch helper for the backend API.
 * `path` is relative to NEXT_PUBLIC_API_URL, e.g. "/health".
 */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");

  const response = await fetch(`${getApiUrl()}${path}`, { ...init, headers });

  if (!response.ok) {
    let message = response.statusText || "Request failed";
    try {
      const body = (await response.json()) as ApiErrorBody;
      if (body.detail) message = body.detail;
    } catch {
      // Non-JSON error body: keep the status text.
    }
    throw new ApiError(response.status, message);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
