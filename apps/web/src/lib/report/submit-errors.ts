import { isApiError } from "@/lib/api";
import type { ReportStep } from "./draft";

/*
 * What to tell the citizen, and where to send them, when submitting a
 * report fails. Every error code the contract lists for POST /reports has
 * an entry, plus the generic ones that can happen on any request.
 */

export type SubmitErrorKey =
  | "network"
  | "server"
  | "rate_limited"
  | "out_of_jurisdiction"
  | "evidence_required"
  | "invalid_media"
  | "validation"
  | "idempotency_key_reused"
  | "signed_out"
  | "forbidden"
  | "unknown";

export type SubmitErrorInfo = {
  /** Message under `report.submitErrors.*`. */
  key: SubmitErrorKey;
  /** The step that needs fixing, offered as a button. */
  step?: ReportStep;
  /** Sending the same draft again may work (and is safe: same key). */
  retryable: boolean;
  /** Seconds to wait, for rate limiting. */
  retryAfter?: number;
  /** Per-field problems from a validation_error, keyed by detail field. */
  fields?: string[];
};

function fieldKeys(details: Record<string, unknown>): string[] {
  // The envelope's details for validation_error are per field. Accept
  // `{ fields: { key: msg } }`, `{ details: { key: msg } }` or flat keys.
  const nested = details.fields ?? details.details;
  const source =
    nested && typeof nested === "object"
      ? (nested as Record<string, unknown>)
      : details;
  return Object.keys(source).filter((key) => key !== "retry_after");
}

export function submitErrorInfo(error: unknown): SubmitErrorInfo {
  if (!isApiError(error)) return { key: "unknown", retryable: true };
  switch (error.code) {
    case "network_error":
      return { key: "network", retryable: true };
    case "internal_error":
    case "invalid_response":
      return { key: "server", retryable: true };
    case "rate_limited":
      return {
        key: "rate_limited",
        retryable: true,
        retryAfter: error.retryAfter ?? undefined,
      };
    case "out_of_jurisdiction":
      return { key: "out_of_jurisdiction", step: 2, retryable: false };
    case "evidence_required":
      return { key: "evidence_required", step: 1, retryable: false };
    case "invalid_media":
      return { key: "invalid_media", step: 1, retryable: false };
    case "validation_error":
      return {
        key: "validation",
        step: 3,
        retryable: false,
        fields: fieldKeys(error.details),
      };
    case "idempotency_key_reused":
      return { key: "idempotency_key_reused", retryable: false };
    case "unauthenticated":
    case "token_expired":
      return { key: "signed_out", retryable: false };
    case "forbidden":
    case "tenant_mismatch":
      return { key: "forbidden", retryable: false };
    default:
      return {
        key: error.status >= 500 ? "server" : "unknown",
        retryable: true,
      };
  }
}
