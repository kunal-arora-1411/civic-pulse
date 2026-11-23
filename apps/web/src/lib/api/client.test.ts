import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { z } from "zod";
import { makeUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { apiRequest } from "./client";
import { ApiError } from "./errors";
import { session } from "./session";

afterEach(() => session.reset());

describe("apiRequest", () => {
  it("names the tenant on anonymous requests", async () => {
    let headers: Headers | undefined;
    server.use(
      http.get(`${API}/tenants/current`, ({ request }) => {
        headers = request.headers;
        return HttpResponse.json({ ok: true });
      }),
    );

    await apiRequest({
      path: "/tenants/current",
      schema: z.object({ ok: z.boolean() }),
    });

    expect(headers?.get("X-Tenant")).toBe("demo-city");
    expect(headers?.get("Authorization")).toBeNull();
    expect(headers?.get("X-Request-ID")).toBeTruthy();
  });

  it("sends the bearer token, and no X-Tenant, once signed in", async () => {
    session.setAuthenticated("token-abc", makeUser());
    let headers: Headers | undefined;
    server.use(
      http.get(`${API}/users/me`, ({ request }) => {
        headers = request.headers;
        return HttpResponse.json({});
      }),
    );

    await apiRequest({ path: "/users/me", schema: z.object({}) });

    expect(headers?.get("Authorization")).toBe("Bearer token-abc");
    expect(headers?.get("X-Tenant")).toBeNull();
  });

  it("serialises query params and drops empty ones", async () => {
    let url: URL | undefined;
    server.use(
      http.get(`${API}/admin/users`, ({ request }) => {
        url = new URL(request.url);
        return HttpResponse.json({});
      }),
    );

    await apiRequest({
      path: "/admin/users",
      query: {
        q: "asha",
        role: undefined,
        is_active: false,
        offset: 0,
        sort: "",
      },
      schema: z.object({}),
    });

    expect(Object.fromEntries(url?.searchParams ?? [])).toEqual({
      q: "asha",
      is_active: "false",
      offset: "0",
    });
  });

  it("passes the idempotency key through", async () => {
    let key: string | null = null;
    server.use(
      http.post(`${API}/admin/users`, ({ request }) => {
        key = request.headers.get("Idempotency-Key");
        return HttpResponse.json({});
      }),
    );

    await apiRequest({
      method: "POST",
      path: "/admin/users",
      body: {},
      schema: z.object({}),
      idempotencyKey: "key-1",
    });

    expect(key).toBe("key-1");
  });

  it("throws a typed ApiError for error envelopes", async () => {
    server.use(
      http.get(`${API}/admin/users`, () =>
        HttpResponse.json(
          { error: { code: "forbidden", message: "No.", request_id: "r1" } },
          { status: 403 },
        ),
      ),
    );

    const error = await apiRequest({ path: "/admin/users" }).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 403,
      code: "forbidden",
      requestId: "r1",
    });
  });

  it("flags responses that don't match the schema", async () => {
    server.use(
      http.get(`${API}/users/me`, () => HttpResponse.json({ id: 42 })),
    );

    const error = await apiRequest({
      path: "/users/me",
      schema: z.object({ id: z.string() }),
    }).catch((e) => e);

    expect(error).toMatchObject({ code: "invalid_response", status: 200 });
  });

  it("reports network failures as network_error", async () => {
    server.use(http.get(`${API}/users/me`, () => HttpResponse.error()));

    const error = await apiRequest({ path: "/users/me" }).catch((e) => e);
    expect(error).toMatchObject({ code: "network_error", status: 0 });
  });

  it("resolves 204 responses to undefined", async () => {
    server.use(
      http.post(
        `${API}/auth/logout`,
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    await expect(
      apiRequest({ method: "POST", path: "/auth/logout" }),
    ).resolves.toBeUndefined();
  });
});
