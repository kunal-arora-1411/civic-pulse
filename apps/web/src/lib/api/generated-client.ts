import {
  configureRequester,
  type RequestConfig,
  type RequestOptions,
} from "@civicpulse/api-client";
import type { z } from "zod";
import { apiRequest, type QueryValue } from "./client";

/*
 * Glue between the orval-generated client (@civicpulse/api-client) and
 * `apiRequest`, which stays the single HTTP entry point. The generated
 * functions describe each operation (path, method, query, body); this file
 * turns that description into an `apiRequest` call, so auth headers,
 * X-Tenant, the single-flight token refresh, idempotency keys and ApiError
 * mapping all behave exactly as for hand-written calls.
 */

/** The spec's paths include the version prefix; API_BASE already has it. */
const API_PREFIX = "/api/v1";

export function toApiPath(url: string): string {
  if (url === API_PREFIX || url.startsWith(`${API_PREFIX}/`)) {
    return url.slice(API_PREFIX.length) || "/";
  }
  throw new Error(`Generated request outside ${API_PREFIX}: ${url}`);
}

/** The requester the generated client calls for every request. */
export function orvalRequester(
  config: RequestConfig,
  options: RequestOptions,
): Promise<unknown> {
  return apiRequest<unknown>({
    method: config.method,
    path: toApiPath(config.url),
    query: config.params as Record<string, QueryValue> | undefined,
    body: config.data,
    // orval adds `Content-Type: application/json` for JSON bodies, which
    // apiRequest sets anyway; per-call headers win over both.
    headers: { ...config.headers, ...options.headers },
    schema: options.schema as z.ZodType<unknown> | undefined,
    signal: options.signal ?? config.signal,
    idempotencyKey: options.idempotencyKey,
    auth: options.auth,
    tenant: options.tenant,
    credentials: options.credentials,
  });
}

configureRequester(orvalRequester);

/**
 * Call a generated function and validate its response with `schema`.
 *
 * Generated functions are typed with the spec's shapes; the app's schemas
 * are those shapes plus small adapters (defaults, `null` for missing
 * values, tuples). `apiRequest` parses the response with `schema`, so the
 * resolved value really is `z.output<typeof schema>` and the cast below is
 * what makes the types say so. A response that doesn't match still fails
 * with `invalid_response`.
 */
export function call<S extends z.ZodType>(
  schema: S,
  run: (options: RequestOptions) => Promise<unknown>,
  options: Omit<RequestOptions, "schema"> = {},
): Promise<z.output<S>> {
  return run({ ...options, schema }) as Promise<z.output<S>>;
}

/** For operations whose response body the app doesn't read (204s and the like). */
export async function callVoid(
  run: (options: RequestOptions) => Promise<unknown>,
  options: Omit<RequestOptions, "schema"> = {},
): Promise<void> {
  await run(options);
}

type MutableArray<V> = V extends readonly (infer U)[] ? U[] : V;
export type MutableArrays<T> = { [K in keyof T]: MutableArray<T[K]> };

/**
 * The generated params types use mutable arrays, while the app's filter
 * types are readonly. Nothing on the way mutates them (`buildUrl` only
 * reads), so this changes the type only; element types are still checked.
 */
export function queryParams<T extends object>(params: T): MutableArrays<T> {
  return params as MutableArrays<T>;
}
