"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";
import { isApiError } from "@/lib/api";

const TRANSLATED = [
  "network_error",
  "invalid_response",
  "unauthenticated",
  "token_expired",
  "forbidden",
  "tenant_mismatch",
  "not_found",
  "conflict",
  "rate_limited",
  "validation_error",
  "idempotency_key_reused",
  "invalid_code",
  "code_expired",
  "internal_error",
  "unsupported_media_type",
  "file_too_large",
  "upload_verification_failed",
  "upload_failed",
  "out_of_jurisdiction",
  "evidence_required",
  "invalid_media",
  "version_conflict",
  "invalid_transition",
  "reason_required",
] as const;

export type ErrorMessageKey =
  | (typeof TRANSLATED)[number]
  | "rate_limited_wait"
  | "unknown";

export type ErrorMessage = {
  key: ErrorMessageKey;
  values?: Record<string, number>;
};

/**
 * Which `errors.*` message describes a thrown value. Server messages are
 * English-only, so they're never shown directly; unknown codes and
 * non-API errors fall back to a generic message.
 */
export function errorMessageFor(error: unknown): ErrorMessage {
  if (!isApiError(error)) return { key: "unknown" };
  if (error.code === "rate_limited" && error.retryAfter) {
    return { key: "rate_limited_wait", values: { seconds: error.retryAfter } };
  }
  return (TRANSLATED as readonly string[]).includes(error.code)
    ? { key: error.code as ErrorMessageKey }
    : { key: "unknown" };
}

/** Map any thrown value to a message in the user's language. */
export function useErrorMessage(): (error: unknown) => string {
  const t = useTranslations("errors");
  return useCallback(
    (error: unknown) => {
      const { key, values } = errorMessageFor(error);
      return t(key, values);
    },
    [t],
  );
}
