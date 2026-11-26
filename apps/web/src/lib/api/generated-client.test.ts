import {
  configureRequester,
  issuesList,
  usersGetMe,
} from "@civicpulse/api-client";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { z } from "zod";
import { makeTokenResponse, makeUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { listIssues, removeRelatedIssue } from "./endpoints/issues";
import { createReport } from "./endpoints/reports";
import { getMe } from "./endpoints/users";
import { ApiError } from "./errors";
import { call, orvalRequester, toApiPath } from "./generated-client";
import { session } from "./session";

afterEach(() => session.reset());

describe("toApiPath", () => {
  it("strips the version prefix the spec's paths carry", () => {
    expect(toApiPath("/api/v1/users/me")).toBe("/users/me");
    expect(toApiPath("/api/v1/issues/a%2Fb")).toBe("/issues/a%2Fb");
  });

  it("refuses paths outside the versioned API", () => {
    expect(() => toApiPath("/health")).toThrow();
    expect(() => toApiPath("/api/v10/x")).toThrow();
  });
});

describe("requester wiring", () => {
  it("rejects clearly when no requester is installed", async () => {
    configureRequester(null);
    try {
      await expect(usersGetMe()).rejects.toThrow(/no requester configured/);
    } finally {
      configureRequester(orvalRequester);
    }
  });
});

describe("generated client through apiRequest", () => {
  it("names the tenant on anonymous calls and the token once signed in", async () => {
    const seen: Headers[] = [];
    server.use(
      http.get(`${API}/users/me`, ({ request }) => {
        seen.push(request.headers);
        return HttpResponse.json(makeUser());
      }),
    );

    await call(z.unknown(), (o) => usersGetMe(o));
    session.setAuthenticated("token-abc", makeUser());
    await call(z.unknown(), (o) => usersGetMe(o));

    expect(seen[0].get("X-Tenant")).toBe("demo-city");
    expect(seen[0].get("Authorization")).toBeNull();
    expect(seen[1].get("Authorization")).toBe("Bearer token-abc");
    expect(seen[1].get("X-Tenant")).toBeNull();
  });

  it("validates with the schema passed in, adapters included", async () => {
    session.setAuthenticated("token-abc", makeUser());
    const { preferences: _omitted, ...user } = makeUser({
      roles: [{ role: "citizen" } as never],
    });
    server.use(http.get(`${API}/users/me`, () => HttpResponse.json(user)));

    const me = await getMe();

    // Adapters on top of the generated UserMe schema.
    expect(me.preferences).toEqual({});
    expect(me.roles[0]).toEqual({
      role: "citizen",
      department_id: null,
      jurisdiction_id: null,
    });
  });

  it("fails with invalid_response when the body doesn't match", async () => {
    session.setAuthenticated("token-abc", makeUser());
    server.use(http.get(`${API}/users/me`, () => HttpResponse.json({ id: 1 })));

    const error = await getMe().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("invalid_response");
  });

  it("serialises query arrays as repeated keys and drops empty values", async () => {
    session.setAuthenticated("token-abc", makeUser());
    let url: URL | undefined;
    server.use(
      http.get(`${API}/issues`, ({ request }) => {
        url = new URL(request.url);
        return HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 });
      }),
    );

    await listIssues({
      status: ["reported", "verified"],
      priority_band: ["high"],
      q: "",
      limit: 20,
    });

    expect(url?.searchParams.getAll("status")).toEqual([
      "reported",
      "verified",
    ]);
    expect(url?.searchParams.getAll("priority_band")).toEqual(["high"]);
    expect(url?.searchParams.has("q")).toBe(false);
    expect(url?.searchParams.get("limit")).toBe("20");
  });

  it("encodes path parameters", async () => {
    session.setAuthenticated("token-abc", makeUser());
    let path: string | undefined;
    server.use(
      http.delete(`${API}/issues/:id/related/:other`, ({ request }) => {
        path = new URL(request.url).pathname;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await removeRelatedIssue("a b", "c/d");

    expect(path).toBe("/api/v1/issues/a%20b/related/c%2Fd");
  });

  it("sends the JSON body and the idempotency key", async () => {
    session.setAuthenticated("token-abc", makeUser());
    let request: Request | undefined;
    let body: unknown;
    server.use(
      http.post(`${API}/reports`, async (info) => {
        request = info.request;
        body = await info.request.json();
        return HttpResponse.json({ unexpected: true }, { status: 201 });
      }),
    );

    const draft = {
      category_id: "cat-pothole",
      description: "Pothole",
      location: { lat: 12.97, lng: 77.59, accuracy_m: 10, source: "gps" },
      details: {},
      media_ids: ["m-1"],
      client_created_at: "2026-11-24T08:00:00Z",
    } as const;
    await createReport(
      { ...draft, media_ids: [...draft.media_ids] },
      { idempotencyKey: "key-1" },
    ).catch(() => undefined);

    expect(request?.method).toBe("POST");
    expect(request?.headers.get("Idempotency-Key")).toBe("key-1");
    expect(request?.headers.get("Content-Type")).toBe("application/json");
    expect(body).toEqual(draft);
  });

  it("refreshes an expired token once and retries the generated call", async () => {
    session.setAuthenticated("stale", makeUser());
    let refreshCalls = 0;
    server.use(
      http.get(`${API}/issues`, ({ request }) =>
        request.headers.get("Authorization") === "Bearer fresh"
          ? HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 })
          : HttpResponse.json(
              { error: { code: "token_expired", message: "Expired." } },
              { status: 401 },
            ),
      ),
      http.post(`${API}/auth/refresh`, async () => {
        refreshCalls += 1;
        await new Promise((resolve) => setTimeout(resolve, 10));
        return HttpResponse.json(makeTokenResponse(makeUser(), "fresh"));
      }),
    );

    const results = await Promise.all([
      call(z.unknown(), (o) => issuesList({}, o)),
      call(z.unknown(), (o) => issuesList({ status: ["reported"] }, o)),
    ]);

    expect(results).toHaveLength(2);
    expect(refreshCalls).toBe(1);
    expect(session.getAccessToken()).toBe("fresh");
  });

  it("maps error envelopes to ApiError", async () => {
    session.setAuthenticated("token-abc", makeUser());
    server.use(
      http.delete(`${API}/issues/:id/related/:other`, () =>
        HttpResponse.json(
          { error: { code: "not_found", message: "No such link." } },
          { status: 404 },
        ),
      ),
    );

    const apiError = await removeRelatedIssue("i", "j").catch(
      (e: unknown) => e,
    );
    expect(apiError).toBeInstanceOf(ApiError);
    expect((apiError as ApiError).code).toBe("not_found");
    expect((apiError as ApiError).status).toBe(404);
  });
});
