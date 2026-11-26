import type { z } from "zod";

/*
 * orval's custom mutator. Every generated request function in
 * ./generated/endpoints.ts ends in `customInstance(config, options)`.
 *
 * The package doesn't do HTTP itself: the app supplies the transport with
 * `configureRequester` (the web app plugs in its `apiRequest`, which owns
 * auth headers, X-Tenant, the single-flight token refresh, idempotency keys
 * and error mapping). That keeps this package free of app code and lets
 * the dependency point one way, from the app to the generated client.
 */

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

/** What a generated function describes: the operation's HTTP exchange. */
export type RequestConfig = {
  /** Full path from the spec, including the `/api/v1` prefix. */
  url: string;
  method: HttpMethod;
  /** Query parameters. Arrays mean repeated keys (`status=a&status=b`). */
  params?: object;
  /** JSON request body. */
  data?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
};

/**
 * Per-call options a caller passes as a generated function's last
 * argument. They are forwarded untouched to the requester.
 */
export type RequestOptions = {
  /** Validates and types the JSON response. Omit for 204 responses. */
  schema?: z.ZodType;
  signal?: AbortSignal;
  headers?: Record<string, string>;
  idempotencyKey?: string;
  /** Attach the access token (default true). */
  auth?: boolean;
  /** Send `X-Tenant` when there's no token (default true). */
  tenant?: boolean;
  credentials?: RequestCredentials;
};

export type Requester = (
  config: RequestConfig,
  options: RequestOptions,
) => Promise<unknown>;

let requester: Requester | null = null;

/** Install the transport. Call once, before any request is made. */
export function configureRequester(next: Requester | null): void {
  requester = next;
}

export function customInstance<T>(
  config: RequestConfig,
  options?: RequestOptions,
): Promise<T> {
  if (!requester) {
    return Promise.reject(
      new Error(
        "@civicpulse/api-client: no requester configured. Call configureRequester() first.",
      ),
    );
  }
  return requester(config, options ?? {}) as Promise<T>;
}
