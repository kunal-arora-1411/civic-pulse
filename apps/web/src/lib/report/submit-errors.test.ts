import { describe, expect, it } from "vitest";
import { errorMessageFor } from "@/hooks/use-error-message";
import { ApiError } from "@/lib/api";
import messages from "../../../messages/en.json";
import hiMessages from "../../../messages/hi.json";
import { submitErrorInfo } from "./submit-errors";

const apiError = (
  code: string,
  status = 422,
  extra: Partial<ConstructorParameters<typeof ApiError>[0]> = {},
) => new ApiError({ status, code, message: code, ...extra });

describe("submitErrorInfo", () => {
  it.each([
    ["network_error", 0, { key: "network", retryable: true }],
    ["internal_error", 500, { key: "server", retryable: true }],
    ["invalid_response", 200, { key: "server", retryable: true }],
    ["service_unavailable", 503, { key: "server", retryable: true }],
    [
      "out_of_jurisdiction",
      422,
      { key: "out_of_jurisdiction", step: 2, retryable: false },
    ],
    [
      "evidence_required",
      422,
      { key: "evidence_required", step: 1, retryable: false },
    ],
    ["invalid_media", 422, { key: "invalid_media", step: 1, retryable: false }],
    [
      "idempotency_key_reused",
      422,
      { key: "idempotency_key_reused", retryable: false },
    ],
    ["unauthenticated", 401, { key: "signed_out", retryable: false }],
    ["token_expired", 401, { key: "signed_out", retryable: false }],
    ["forbidden", 403, { key: "forbidden", retryable: false }],
    ["something_new", 400, { key: "unknown", retryable: true }],
  ] as const)("maps %s", (code, status, expected) => {
    expect(submitErrorInfo(apiError(code, status))).toMatchObject(expected);
  });

  it("sends validation errors to the details step with the field names", () => {
    expect(
      submitErrorInfo(
        apiError("validation_error", 422, {
          details: { fields: { size: "not an option" } },
        }),
      ),
    ).toEqual({
      key: "validation",
      step: 3,
      retryable: false,
      fields: ["size"],
    });
  });

  it("passes the wait time on for rate limiting", () => {
    expect(
      submitErrorInfo(apiError("rate_limited", 429, { retryAfter: 30 })),
    ).toEqual({ key: "rate_limited", retryable: true, retryAfter: 30 });
  });

  it("treats a thrown non-API error as retryable", () => {
    expect(submitErrorInfo(new TypeError("boom"))).toEqual({
      key: "unknown",
      retryable: true,
    });
  });

  it("has an English and a Hindi message for every outcome", () => {
    const keys = [
      "network",
      "server",
      "rate_limited",
      "rate_limited_wait",
      "out_of_jurisdiction",
      "evidence_required",
      "invalid_media",
      "validation",
      "idempotency_key_reused",
      "signed_out",
      "forbidden",
      "unknown",
    ];
    for (const key of keys) {
      expect(messages.report.submitErrors).toHaveProperty(key);
      expect(hiMessages.report.submitErrors).toHaveProperty(key);
    }
  });
});

describe("errorMessageFor", () => {
  it.each([
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
  ])("has a translated message for %s", (code) => {
    const { key } = errorMessageFor(apiError(code));
    expect(key).toBe(code);
    expect(messages.errors).toHaveProperty(code);
    expect(hiMessages.errors).toHaveProperty(code);
  });

  it("falls back for unknown codes and non-API errors", () => {
    expect(errorMessageFor(apiError("brand_new_code"))).toEqual({
      key: "unknown",
    });
    expect(errorMessageFor(new Error("x"))).toEqual({ key: "unknown" });
  });

  it("includes the wait for rate limiting", () => {
    expect(
      errorMessageFor(apiError("rate_limited", 429, { retryAfter: 12 })),
    ).toEqual({ key: "rate_limited_wait", values: { seconds: 12 } });
  });
});
