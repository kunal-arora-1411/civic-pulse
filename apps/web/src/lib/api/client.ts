import type { z } from "zod";
import { API_BASE, TENANT } from "./config";
import { ApiError, isApiError, parseErrorResponse } from "./errors";
import { type TokenResponse, tokenResponseSchema } from "./schemas";
import { session } from "./session";

type QueryScalar = string | number | boolean | null | undefined;
/** Arrays become repeated keys (`status=a&status=b`), as the contract expects. */
export type QueryValue = QueryScalar | readonly QueryScalar[];

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
    const values = Array.isArray(value) ? value : [value];
    for (const item of values) {
      if (item === undefined || item === null || item === "") continue;
      url.searchParams.append(key, String(item));
    }
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

/** A response kept as a file: the body plus the headers describing it. */
export type FileResponse = {
  blob: Blob;
  /** From `Content-Disposition`, when the server names the file. */
  filename: string | null;
  headers: Headers;
};

/** Perform one HTTP exchange and decode it. No retries. */
export async function send<T>(options: RequestOptions<T>): Promise<T> {
  return decode(await perform(options), options.schema);
}

/** Perform one HTTP exchange and keep the body as a file. No retries. */
async function sendFile(options: RequestOptions<never>): Promise<FileResponse> {
  const response = await perform(options);
  return {
    blob: await response.blob(),
    filename: filenameFrom(response.headers.get("Content-Disposition")),
    headers: response.headers,
  };
}

/** One HTTP exchange, keeping the Response so it can be decoded either way. */
async function perform(options: RequestOptions<unknown>): Promise<Response> {
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
  return response;
}

/** `attachment; filename="issues-….csv"` → `issues-….csv`. */
function filenameFrom(header: string | null): string | null {
  if (!header) return null;
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
  if (!match) return null;
  const name = match[1].trim();
  try {
    return decodeURIComponent(name);
  } catch {
    return name;
  }
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
  return withSessionRetry(options, () => send(options));
}

/**
 * Fetch a file instead of JSON — the analytics CSV, for one. Same auth,
 * tenant header and refresh-on-expiry behaviour as `apiRequest`, so a
 * download never needs its own token handling.
 */
export async function apiDownload(
  options: RequestOptions<never>,
): Promise<FileResponse> {
  return withSessionRetry(options, () => sendFile(options));
}

/**
 * Run one attempt, and once more after a successful refresh if the access
 * token had expired. A revoked session is dropped, so guards redirect.
 */
async function withSessionRetry<T>(
  options: Pick<RequestOptions<unknown>, "auth">,
  attempt: () => Promise<T>,
): Promise<T> {
  const usedToken = options.auth === false ? null : session.getAccessToken();
  try {
    return await attempt();
  } catch (error) {
    if (!usedToken || !isApiError(error)) throw error;

    if (error.code === "token_expired") {
      const current = session.getAccessToken();
      // Another request may already have refreshed while this one was in
      // flight; if so, just retry with the newer token.
      if (current && current !== usedToken) return attempt();
      const refreshed = await refreshSession().catch(() => null);
      if (refreshed) return attempt();
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
