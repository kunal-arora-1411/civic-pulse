import type { z } from "zod";
import { API_BASE, TENANT } from "./config";
import { ApiError, isApiError, parseErrorResponse } from "./errors";
import { type TokenResponse, tokenResponseSchema } from "./schemas";
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
  const usedToken = options.auth === false ? null : session.getAccessToken();
  try {
    return await send(options);
  } catch (error) {
    if (!usedToken || !isApiError(error)) throw error;

    if (error.code === "token_expired") {
      const current = session.getAccessToken();
      // Another request may already have refreshed while this one was in
      // flight; if so, just retry with the newer token.
      if (current && current !== usedToken) return send(options);
      const refreshed = await refreshSession().catch(() => null);
      if (refreshed) return send(options);
      throw error;
    }

    if (error.code === "unauthenticated") {
      // The session was revoked server-side (logout elsewhere, reuse
      // detection). Drop local state so guards send the user to /login.
      session.clear();
    }
    throw error;
  }
}

let refreshInFlight: Promise<TokenResponse | null> | null = null;

/**
 * Exchange the refresh cookie for a new access token.
 *
 * Resolves to the token response, or `null` when there's no valid session
 * (the session is then cleared). Network and server errors reject, so a
 * flaky connection isn't mistaken for being signed out.
 *
 * Calls are single-flight: concurrent callers share one request. That's
 * more than an optimisation. Refresh tokens rotate on every use, and the
 * backend revokes the whole session family if one is presented twice, so
 * two parallel refreshes (several 401s at once, or React Strict Mode
 * running the restore effect twice) would log the user out. Across tabs,
 * the Web Locks API serialises refreshes so a second tab waits and then
 * uses the already-rotated cookie.
 */
export function refreshSession(): Promise<TokenResponse | null> {
  if (!refreshInFlight) {
    refreshInFlight = withCrossTabLock(performRefresh).finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

async function performRefresh(): Promise<TokenResponse | null> {
  try {
    const tokens = await send({
      method: "POST",
      path: "/auth/refresh",
      body: {},
      schema: tokenResponseSchema,
      auth: false,
      tenant: false,
      credentials: "include",
    });
    // The body also carries `refresh_token` for non-browser clients. We
    // ignore it on purpose: the browser keeps the HttpOnly cookie.
    session.setAuthenticated(tokens.access_token, tokens.user);
    return tokens;
  } catch (error) {
    if (isApiError(error) && (error.status === 401 || error.status === 403)) {
      session.clear();
      return null;
    }
    throw error;
  }
}

function withCrossTabLock<T>(fn: () => Promise<T>): Promise<T> {
  const locks =
    typeof navigator !== "undefined"
      ? (navigator as Navigator & { locks?: LockManager }).locks
      : undefined;
  // lib.dom types the result as Promise<Promise<T>>; it resolves to T.
  return locks
    ? (locks.request("civicpulse:auth-refresh", fn) as Promise<T>)
    : fn();
}
