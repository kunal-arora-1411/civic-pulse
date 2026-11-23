"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";
import { isApiError } from "@/lib/api";

const translated = new Set([
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
] as const);

type TranslatedCode = typeof translated extends Set<infer C> ? C : never;

/**
 * Map any thrown value to a message in the user's language. Server
 * messages are English-only, so they're never shown directly; unknown
 * codes fall back to a generic message.
 */
export function useErrorMessage(): (error: unknown) => string {
  const t = useTranslations("errors");
  return useCallback(
    (error: unknown) => {
      if (isApiError(error)) {
        if (error.code === "rate_limited" && error.retryAfter) {
          return t("rate_limited_wait", { seconds: error.retryAfter });
        }
        if (translated.has(error.code as TranslatedCode)) {
          return t(error.code as TranslatedCode);
        }
      }
      return t("unknown");
    },
    [t],
  );
}
