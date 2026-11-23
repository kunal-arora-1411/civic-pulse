import { z } from "zod";

/** Error codes from the Phase 0 and 1 contracts, plus client-side ones. */
export type KnownErrorCode =
  | "validation_error"
  | "unauthenticated"
  | "token_expired"
  | "forbidden"
  | "tenant_mismatch"
  | "mfa_required"
  | "not_found"
  | "conflict"
  | "rate_limited"
  | "idempotency_key_reused"
  | "invalid_code"
  | "code_expired"
  | "internal_error"
  // Phase 1: media uploads
  | "unsupported_media_type"
  | "file_too_large"
  | "upload_verification_failed"
  // Phase 1: reports
  | "out_of_jurisdiction"
  | "evidence_required"
  | "invalid_media"
  // Phase 1: issue workflow
  | "version_conflict"
  | "invalid_transition"
  | "reason_required"
  // Client-side: the PUT to object storage failed (network, expiry, CORS).
  | "upload_failed"
  // Client-side: the request never got a response.
  | "network_error"
  // Client-side: the response didn't match the expected schema.
  | "invalid_response";

// Keep autocompletion for known codes while accepting new server codes.
export type ErrorCode = KnownErrorCode | (string & {});

export class ApiError extends Error {
  override readonly name = "ApiError";
  readonly status: number;
  readonly code: ErrorCode;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;
  /** Seconds to wait before retrying, from `Retry-After` or the details. */
  readonly retryAfter: number | null;

  constructor(init: {
    status: number;
    code: ErrorCode;
    message: string;
    details?: Record<string, unknown>;
    requestId?: string | null;
    retryAfter?: number | null;
    cause?: unknown;
  }) {
    super(init.message, { cause: init.cause });
    this.status = init.status;
    this.code = init.code;
    this.details = init.details ?? {};
    this.requestId = init.requestId ?? null;
    this.retryAfter = init.retryAfter ?? null;
  }
}

export function isApiError(
  error: unknown,
  code?: ErrorCode,
): error is ApiError {
  return (
    error instanceof ApiError && (code === undefined || error.code === code)
  );
}

const envelopeSchema = z.object({
  error: z.object({
    code: z.string().min(1),
    message: z.string().default(""),
    details: z.record(z.string(), z.unknown()).nullish(),
    request_id: z.string().nullish(),
  }),
});

function fallbackCode(status: number): ErrorCode {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 422) return "validation_error";
  if (status === 429) return "rate_limited";
  return "internal_error";
}

function parseRetryAfter(
  header: string | null,
  details: Record<string, unknown>,
): number | null {
  const fromDetails = details.retry_after;
  if (typeof fromDetails === "number" && Number.isFinite(fromDetails)) {
    return Math.max(0, Math.ceil(fromDetails));
  }
  if (!header) return null;
  const seconds = Number(header);
  if (Number.isFinite(seconds)) return Math.max(0, Math.ceil(seconds));
  const date = Date.parse(header);
  if (Number.isNaN(date)) return null;
  return Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

/**
 * Turn a non-2xx response into an ApiError. Bodies that don't follow the
 * contract's envelope (a proxy's HTML error page, an empty 502) still give
 * a usable error with a code derived from the status.
 */
export async function parseErrorResponse(
  response: Response,
): Promise<ApiError> {
  const headerRequestId = response.headers.get("X-Request-ID");
  let body: unknown = null;
  try {
    const text = await response.text();
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }

  const parsed = envelopeSchema.safeParse(body);
  if (parsed.success) {
    const { code, message, details, request_id } = parsed.data.error;
    const safeDetails = details ?? {};
    return new ApiError({
      status: response.status,
      code,
      message: message || response.statusText || code,
      details: safeDetails,
      requestId: request_id ?? headerRequestId,
      retryAfter: parseRetryAfter(
        response.headers.get("Retry-After"),
        safeDetails,
      ),
    });
  }

  return new ApiError({
    status: response.status,
    code: fallbackCode(response.status),
    message:
      response.statusText || `Request failed with status ${response.status}`,
    requestId: headerRequestId,
    retryAfter: parseRetryAfter(response.headers.get("Retry-After"), {}),
  });
}
