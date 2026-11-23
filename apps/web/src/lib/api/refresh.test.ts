import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { makeTokenResponse, makeUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { apiRequest, refreshSession } from "./client";
import { logout, restoreSession } from "./endpoints/auth";
import { session } from "./session";

const expired = () =>
  HttpResponse.json(
    { error: { code: "token_expired", message: "Token expired." } },
    { status: 401 },
  );

/** A protected endpoint that only accepts the given token. */
function protectedEndpoint(path: string, validToken: string) {
  return http.get(`${API}${path}`, ({ request }) =>
    request.headers.get("Authorization") === `Bearer ${validToken}`
      ? HttpResponse.json({ path })
      : expired(),
  );
}

const pathSchema = z.object({ path: z.string() });

beforeEach(() => session.setAuthenticated("stale", makeUser()));
afterEach(() => session.reset());

describe("token refresh", () => {
  it("refreshes once for concurrent 401s and retries each request", async () => {
    let refreshCalls = 0;
    server.use(
      protectedEndpoint("/a", "fresh"),
      protectedEndpoint("/b", "fresh"),
      protectedEndpoint("/c", "fresh"),
      http.post(`${API}/auth/refresh`, async () => {
        refreshCalls += 1;
        // Hold the refresh open so every request is waiting on it.
        await new Promise((resolve) => setTimeout(resolve, 20));
        return HttpResponse.json(makeTokenResponse(makeUser(), "fresh"));
      }),
    );

    const results = await Promise.all(
      ["/a", "/b", "/c"].map((path) =>
        apiRequest({ path, schema: pathSchema }),
      ),
    );

    expect(results.map((r) => r.path)).toEqual(["/a", "/b", "/c"]);
    expect(refreshCalls).toBe(1);
    expect(session.getAccessToken()).toBe("fresh");
  });

  it("retries without refreshing when another request already did", async () => {
    let refreshCalls = 0;
    let calls = 0;
    server.use(
      http.get(`${API}/slow`, ({ request }) => {
        calls += 1;
        if (calls === 1) {
          // Another request rotates the token while this one is in flight.
          session.setAuthenticated("fresh", makeUser());
          return expired();
        }
        return request.headers.get("Authorization") === "Bearer fresh"
          ? HttpResponse.json({ path: "/slow" })
          : expired();
      }),
      http.post(`${API}/auth/refresh`, () => {
        refreshCalls += 1;
        return HttpResponse.json(makeTokenResponse());
      }),
    );

    await expect(
      apiRequest({ path: "/slow", schema: pathSchema }),
    ).resolves.toEqual({ path: "/slow" });
    expect(calls).toBe(2);
    expect(refreshCalls).toBe(0);
  });

  it("gives up after one retry", async () => {
    let refreshCalls = 0;
    server.use(
      http.get(`${API}/always-expired`, expired),
      http.post(`${API}/auth/refresh`, () => {
        refreshCalls += 1;
        return HttpResponse.json(makeTokenResponse(makeUser(), "fresh"));
      }),
    );

    const error = await apiRequest({ path: "/always-expired" }).catch((e) => e);
    expect(error).toMatchObject({ code: "token_expired" });
    expect(refreshCalls).toBe(1);
  });

  it("signs out and surfaces the original error when refresh fails", async () => {
    server.use(
      http.get(`${API}/a`, expired),
      http.post(`${API}/auth/refresh`, () =>
        HttpResponse.json(
          { error: { code: "unauthenticated", message: "Session revoked." } },
          { status: 401 },
        ),
      ),
    );

    const error = await apiRequest({ path: "/a" }).catch((e) => e);
    expect(error).toMatchObject({ code: "token_expired" });
    expect(session.getSnapshot()).toEqual({ status: "anonymous", user: null });
    expect(session.getAccessToken()).toBeNull();
  });

  it("clears the session on a plain 401 unauthenticated", async () => {
    server.use(
      http.get(`${API}/a`, () =>
        HttpResponse.json(
          { error: { code: "unauthenticated", message: "Revoked." } },
          { status: 401 },
        ),
      ),
    );

    await apiRequest({ path: "/a" }).catch(() => undefined);
    expect(session.getSnapshot().status).toBe("anonymous");
  });

  it("sends the refresh cookie and no tenant header", async () => {
    let seen: Request | undefined;
    server.use(
      http.post(`${API}/auth/refresh`, ({ request }) => {
        seen = request;
        return HttpResponse.json(makeTokenResponse());
      }),
    );
    // Node's fetch doesn't keep `credentials` on the intercepted Request,
    // so check what the client passed to fetch instead.
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    await refreshSession();

    expect(fetchSpy.mock.calls[0]?.[1]?.credentials).toBe("include");
    expect(seen?.headers.get("X-Tenant")).toBeNull();
    expect(seen?.headers.get("Authorization")).toBeNull();
  });
});

describe("restoreSession", () => {
  beforeEach(() => session.reset());

  it("shares one refresh between overlapping callers", async () => {
    let refreshCalls = 0;
    server.use(
      http.post(`${API}/auth/refresh`, () => {
        refreshCalls += 1;
        return HttpResponse.json(makeTokenResponse(makeUser(), "restored"));
      }),
    );

    // Strict Mode runs mount effects twice in development.
    const [first, second] = await Promise.all([
      restoreSession(),
      restoreSession(),
    ]);

    expect([first, second]).toEqual(["authenticated", "authenticated"]);
    expect(refreshCalls).toBe(1);
    expect(session.getAccessToken()).toBe("restored");
    expect(session.getSnapshot().user?.display_name).toBe("Asha");
  });

  it("reports anonymous when there is no refresh cookie", async () => {
    server.use(
      http.post(`${API}/auth/refresh`, () =>
        HttpResponse.json(
          { error: { code: "unauthenticated", message: "No session." } },
          { status: 401 },
        ),
      ),
    );
    await expect(restoreSession()).resolves.toBe("anonymous");
    expect(session.getSnapshot().status).toBe("anonymous");
  });

  it("reports offline when the API can't be reached", async () => {
    server.use(http.post(`${API}/auth/refresh`, () => HttpResponse.error()));
    await expect(restoreSession()).resolves.toBe("offline");
    expect(session.getSnapshot().status).toBe("anonymous");
  });
});

describe("logout", () => {
  it("clears local state even when the server call fails", async () => {
    server.use(
      http.post(`${API}/auth/logout`, () =>
        HttpResponse.json(
          { error: { code: "internal_error", message: "Boom" } },
          { status: 500 },
        ),
      ),
    );

    await expect(logout()).resolves.toBe(false);
    expect(session.getAccessToken()).toBeNull();
    expect(session.getSnapshot().status).toBe("anonymous");
  });

  it("revokes the session with the bearer token", async () => {
    let auth: string | null = null;
    server.use(
      http.post(`${API}/auth/logout`, ({ request }) => {
        auth = request.headers.get("Authorization");
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await expect(logout()).resolves.toBe(true);
    expect(auth).toBe("Bearer stale");
  });
});
