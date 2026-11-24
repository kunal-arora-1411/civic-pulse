import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { session } from "@/lib/api";
import type { DraftSuggestion } from "@/lib/report/suggestion";
import { makeUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { useCategorySuggestion } from "./use-category-suggestion";

const timing = { debounceMs: 30, pollMs: 10, timeoutMs: 200 };

beforeEach(() => session.setAuthenticated("token", makeUser()));
afterEach(() => session.reset());

function respondDone() {
  const requests: string[][] = [];
  server.use(
    http.post(`${API}/ai/classifications`, async ({ request }) => {
      const body = (await request.json()) as { media_ids: string[] };
      requests.push(body.media_ids);
      return HttpResponse.json({
        id: `cls-${requests.length}`,
        status: "done",
        suggestions: [
          { category_id: "cat-pothole", code: "pothole", confidence: 0.9 },
        ],
      });
    }),
  );
  return requests;
}

describe("useCategorySuggestion", () => {
  it("waits for the photo set to settle, then asks once for the latest set", async () => {
    const requests = respondDone();
    const onResult = vi.fn();
    const { result, rerender } = renderHook(
      ({ ids }: { ids: string[] }) =>
        useCategorySuggestion({
          mediaIds: ids,
          stored: null,
          onResult,
          timing,
        }),
      { initialProps: { ids: ["m1"] } },
    );
    expect(result.current.status).toBe("loading");
    rerender({ ids: ["m1", "m2"] });

    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(requests).toEqual([["m1", "m2"]]);
    expect(onResult).toHaveBeenCalledWith(
      expect.objectContaining({ key: "m1,m2", id: "cls-1" }),
    );
  });

  it("asks again when the photos change after a result", async () => {
    const requests = respondDone();
    const { result, rerender } = renderHook(
      ({ ids }: { ids: string[] }) =>
        useCategorySuggestion({
          mediaIds: ids,
          stored: null,
          onResult: () => {},
          timing,
        }),
      { initialProps: { ids: ["m1"] } },
    );
    await waitFor(() => expect(result.current.status).toBe("done"));
    rerender({ ids: ["m2"] });
    expect(result.current.status).toBe("loading");
    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(requests).toEqual([["m1"], ["m2"]]);
  });

  it("doesn't ask while there are no uploaded photos, or when the draft already has a result", async () => {
    const requests = respondDone();
    const stored: DraftSuggestion = {
      key: "m1",
      id: "cls-old",
      suggestions: [],
      notCivic: false,
      needsManual: true,
    };
    const empty = renderHook(() =>
      useCategorySuggestion({
        mediaIds: [],
        stored: null,
        onResult: () => {},
        timing,
      }),
    );
    const kept = renderHook(() =>
      useCategorySuggestion({
        mediaIds: ["m1"],
        stored,
        onResult: () => {},
        timing,
      }),
    );
    await new Promise((resolve) => setTimeout(resolve, 80));
    expect(empty.result.current.status).toBe("idle");
    expect(kept.result.current).toEqual({ status: "done", suggestion: stored });
    expect(requests).toEqual([]);
  });
});
