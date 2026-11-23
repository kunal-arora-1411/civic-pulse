import { describe, expect, it } from "vitest";
import { ApiError, isApiError, parseErrorResponse } from "./errors";

function jsonResponse(status: number, body: unknown, headers?: HeadersInit) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

describe("parseErrorResponse", () => {
  it("reads code, message, details and request id from the envelope", async () => {
    const error = await parseErrorResponse(
      jsonResponse(422, {
        error: {
          code: "validation_error",
          message: "Phone number is invalid.",
          details: { field: "phone" },
          request_id: "req-123",
        },
      }),
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 422,
      code: "validation_error",
      message: "Phone number is invalid.",
      details: { field: "phone" },
      requestId: "req-123",
      retryAfter: null,
    });
  });

  it("keeps codes the client doesn't know about", async () => {
    const error = await parseErrorResponse(
      jsonResponse(400, { error: { code: "brand_new_code", message: "Nope" } }),
    );
    expect(error.code).toBe("brand_new_code");
    expect(error.details).toEqual({});
  });

  it("falls back to the X-Request-ID header", async () => {
    const error = await parseErrorResponse(
      jsonResponse(
        404,
        { error: { code: "not_found", message: "Missing" } },
        { "X-Request-ID": "from-header" },
      ),
    );
    expect(error.requestId).toBe("from-header");
  });

  it("takes retry-after from details, then from the header", async () => {
    const fromDetails = await parseErrorResponse(
      jsonResponse(
        429,
        {
          error: {
            code: "rate_limited",
            message: "Slow down",
            details: { retry_after: 41.2 },
          },
        },
        { "Retry-After": "5" },
      ),
    );
    expect(fromDetails.retryAfter).toBe(42);

    const fromHeader = await parseErrorResponse(
      jsonResponse(
        429,
        { error: { code: "rate_limited", message: "Slow down" } },
        { "Retry-After": "30" },
      ),
    );
    expect(fromHeader.retryAfter).toBe(30);
  });

  it("derives a code from the status when the body isn't an envelope", async () => {
    const html = new Response("<h1>Bad gateway</h1>", {
      status: 502,
      statusText: "Bad Gateway",
    });
    const error = await parseErrorResponse(html);
    expect(error).toMatchObject({
      status: 502,
      code: "internal_error",
      message: "Bad Gateway",
    });
  });

  it.each([
    [401, "unauthenticated"],
    [403, "forbidden"],
    [404, "not_found"],
    [409, "conflict"],
    [422, "validation_error"],
    [429, "rate_limited"],
  ])("maps a bare %i to %s", async (status, code) => {
    const error = await parseErrorResponse(new Response(null, { status }));
    expect(error.code).toBe(code);
  });

  it("ignores JSON that has the wrong shape", async () => {
    const error = await parseErrorResponse(
      jsonResponse(500, { detail: "Internal Server Error" }),
    );
    expect(error.code).toBe("internal_error");
  });
});

describe("isApiError", () => {
  it("narrows by code", () => {
    const error = new ApiError({
      status: 401,
      code: "token_expired",
      message: "",
    });
    expect(isApiError(error)).toBe(true);
    expect(isApiError(error, "token_expired")).toBe(true);
    expect(isApiError(error, "forbidden")).toBe(false);
    expect(isApiError(new Error("x"))).toBe(false);
  });
});
