import type { z } from "zod";
import { API_BASE, TENANT } from "./config";
import { ApiError, parseErrorResponse } from "./errors";
import { session } from "./session";

type QueryValue = string | number | boolean | null | undefined;

export type RequestOptions<T> = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** Path below /api/v1, e.g. `/users/me`. */
  path: string;
  query?: Record<string, QueryValue>;
  body?: unknown;
  /** Validates and types the JSON response. Omit for 204 responses. */
  schema?: z.ZodType<T>;
  headers?: Record<string, string>;
  idempotencyKey?: string;
  signal?: AbortSignal;
  /**
   * Auth endpoints must send credentials so the browser stores and sends
   * the HttpOnly refresh cookie. Everything else uses the bearer token.
   */
  credentials?: RequestCredentials;
  /** Attach the in-memory access token (default true). */
  auth?: boolean;
  /**
   * Send `X-Tenant` when no token is attached (default true). The refresh
   * call opts out: the refresh token already identifies the tenant, and
   * platform admins have none.
   */
  tenant?: boolean;
};

export function buildUrl(path: string, query?: Record<string, QueryValue>) {
  const url = new URL(`${API_BASE}${path}`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === "") continue;
    url.searchParams.set(key, String(value));
  }
  return url.toString();
}

function requestId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export function buildHeaders(
  options: Pick<
    RequestOptions<unknown>,
    "body" | "headers" | "idempotencyKey" | "auth" | "tenant"
  >,
): Headers {
  const headers = new Headers({ Accept: "application/json" });
  headers.set("X-Request-ID", requestId());
  if (options.body !== undefined)
    headers.set("Content-Type", "application/json");

  const token = options.auth === false ? null : session.getAccessToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  } else if (options.tenant !== false) {
    // Authenticated requests take the tenant from the token, and a
    // mismatching X-Tenant is rejected (403 tenant_mismatch). Only name the
    // tenant when there is no token to carry it.
    headers.set("X-Tenant", TENANT);
  }
  if (options.idempotencyKey) {
    headers.set("Idempotency-Key", options.idempotencyKey);
  }
  for (const [key, value] of Object.entries(options.headers ?? {})) {
    headers.set(key, value);
  }
  return headers;
}

/** Perform one HTTP exchange and decode it. No retries. */
export async function send<T>(options: RequestOptions<T>): Promise<T> {
  let response: Response;
  try {
    response = await fetch(buildUrl(options.path, options.query), {
      method: options.method ?? "GET",
      headers: buildHeaders(options),
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: options.credentials ?? "same-origin",
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError({
      status: 0,
      code: "network_error",
      message: "Could not reach the server.",
      cause: error,
    });
  }

  if (!response.ok) throw await parseErrorResponse(response);
  return decode(response, options.schema);
}

async function decode<T>(
  response: Response,
  schema: z.ZodType<T> | undefined,
): Promise<T> {
  if (!schema || response.status === 204) {
    return undefined as T;
  }
  let json: unknown;
  try {
    json = await response.json();
  } catch (error) {
    throw new ApiError({
      status: response.status,
      code: "invalid_response",
      message: "The server sent a response that isn't JSON.",
      cause: error,
    });
  }
  const parsed = schema.safeParse(json);
  if (!parsed.success) {
    throw new ApiError({
      status: response.status,
      code: "invalid_response",
      message: "The server response didn't match the expected shape.",
      requestId: response.headers.get("X-Request-ID"),
      cause: parsed.error,
    });
  }
  return parsed.data;
}

/**
 * The single entry point feature code uses for HTTP. Its signature is the
 * shape an orval "custom mutator" needs, so a generated client can route
 * through it later and keep the auth and error behaviour.
 */
export async function apiRequest<T = void>(
  options: RequestOptions<T>,
): Promise<T> {
  return send(options);
}
