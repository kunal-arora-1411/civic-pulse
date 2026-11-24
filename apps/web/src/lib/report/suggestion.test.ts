import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { session } from "@/lib/api";
import { makeCategory, makeUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { newDraft, type ReportDraft } from "./draft";
import {
  applySuggestion,
  confidenceWording,
  type DraftSuggestion,
  orderCategories,
  runClassification,
  suggestionKey,
} from "./suggestion";

const timing = { pollMs: 10, timeoutMs: 100 };
const done = {
  id: "cls-1",
  status: "done",
  model_id: "fake@1",
  suggestions: [
    { category_id: "cat-waste", code: "waste", confidence: 0.82 },
    { category_id: "cat-pothole", code: "pothole", confidence: 0.09 },
  ],
  not_civic: false,
  needs_manual: false,
};

beforeEach(() => session.setAuthenticated("token", makeUser()));
afterEach(() => session.reset());

describe("runClassification", () => {
  it("returns a result the API finished within its own wait (200 done)", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post(`${API}/ai/classifications`, async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(done);
      }),
    );
    const outcome = await runClassification(
      ["m1", "m2"],
      new AbortController().signal,
      timing,
    );
    expect(outcome).toMatchObject({ status: "done", result: { id: "cls-1" } });
    expect(bodies).toEqual([{ media_ids: ["m1", "m2"] }]);
  });

  it("polls a pending classification until it's done (202 → done)", async () => {
    let polls = 0;
    server.use(
      http.post(`${API}/ai/classifications`, () =>
        HttpResponse.json({ id: "cls-1", status: "pending" }, { status: 202 }),
      ),
      http.get(`${API}/ai/classifications/cls-1`, () => {
        polls += 1;
        return HttpResponse.json(
          polls < 3 ? { id: "cls-1", status: "pending" } : done,
        );
      }),
    );
    const outcome = await runClassification(
      ["m1"],
      new AbortController().signal,
      timing,
    );
    expect(outcome.status).toBe("done");
    expect(polls).toBe(3);
  });

  it("gives up when the classification stays pending past the timeout", async () => {
    let polls = 0;
    let clock = 0;
    server.use(
      http.post(`${API}/ai/classifications`, () =>
        HttpResponse.json({ id: "cls-1", status: "pending" }, { status: 202 }),
      ),
      http.get(`${API}/ai/classifications/cls-1`, () => {
        polls += 1;
        clock += 10;
        return HttpResponse.json({ id: "cls-1", status: "pending" });
      }),
    );
    // A tenth of the real schedule (1.5 s polls, 15 s limit), on a clock
    // that moves one interval per poll so the count is exact.
    const outcome = await runClassification(
      ["m1"],
      new AbortController().signal,
      { pollMs: 10, timeoutMs: 100 },
      () => clock,
    );
    expect(outcome).toEqual({ status: "failed", reason: "timeout" });
    expect(polls).toBe(10);
  });

  it("treats a failed classification as no suggestion", async () => {
    server.use(
      http.post(`${API}/ai/classifications`, () =>
        HttpResponse.json({
          id: "cls-1",
          status: "failed",
          error: "ai_unavailable",
        }),
      ),
    );
    expect(
      await runClassification(["m1"], new AbortController().signal, timing),
    ).toEqual({ status: "failed", reason: "unavailable" });
  });

  it("treats a server or network error as no suggestion", async () => {
    server.use(
      http.post(`${API}/ai/classifications`, () => HttpResponse.error()),
    );
    expect(
      await runClassification(["m1"], new AbortController().signal, timing),
    ).toEqual({ status: "failed", reason: "error" });
  });
});

const pothole = makeCategory();
const waste = makeCategory({
  id: "cat-waste",
  code: "waste",
  name_i18n: { en: "Garbage" },
  fields: [
    {
      key: "overflowing_bin",
      type: "boolean",
      required: false,
      label_i18n: { en: "Bin overflowing?" },
    },
  ],
});
const categories = [pothole, waste];

const suggestion: DraftSuggestion = {
  key: "m1",
  id: "cls-1",
  suggestions: done.suggestions,
  notCivic: false,
  needsManual: false,
};

function draft(overrides: Partial<ReportDraft> = {}): ReportDraft {
  return { ...newDraft(), step: 3, ...overrides };
}

describe("applySuggestion", () => {
  it("pre-selects the top suggestion and remembers it was shown", () => {
    const next = applySuggestion(draft(), suggestion, categories);
    expect(next).toMatchObject({
      categoryId: "cat-waste",
      categorySource: "ai",
      classificationId: "cls-1",
    });
  });

  it("never replaces a category the citizen picked", () => {
    const mine = draft({
      categoryId: "cat-pothole",
      categorySource: "citizen",
    });
    expect(applySuggestion(mine, suggestion, categories)).toBe(mine);
  });

  it("doesn't pre-select when the model isn't sure or sees no civic problem", () => {
    const empty = draft();
    expect(
      applySuggestion(empty, { ...suggestion, needsManual: true }, categories),
    ).toBe(empty);
    expect(
      applySuggestion(empty, { ...suggestion, notCivic: true }, categories),
    ).toBe(empty);
    expect(applySuggestion(empty, null, categories)).toBe(empty);
  });

  it("ignores a suggestion for a category the citizen can't choose", () => {
    const empty = draft();
    expect(
      applySuggestion(
        empty,
        {
          ...suggestion,
          suggestions: [{ category_id: "gone", code: "x", confidence: 0.9 }],
        },
        categories,
      ),
    ).toBe(empty);
  });

  it("withdraws an earlier pre-selection when new photos give no suggestion", () => {
    const preselected = applySuggestion(draft(), suggestion, categories);
    expect(applySuggestion(preselected, null, categories)).toMatchObject({
      categoryId: null,
      categorySource: null,
      classificationId: null,
    });
  });

  it("keeps answers only for fields the suggested category also has", () => {
    const next = applySuggestion(
      draft({ details: { size: "large", overflowing_bin: true } }),
      suggestion,
      categories,
    );
    expect(next.details).toEqual({ overflowing_bin: true });
  });
});

describe("orderCategories", () => {
  it("puts the suggestions first, best first, once shown", () => {
    const drain = makeCategory({ id: "cat-drain", code: "drainage" });
    expect(orderCategories([pothole, drain, waste], suggestion, true)).toEqual({
      suggested: [waste, pothole],
      others: [drain],
    });
  });

  it("keeps the usual order until a suggestion has been shown", () => {
    expect(orderCategories(categories, suggestion, false)).toEqual({
      suggested: [],
      others: categories,
    });
  });
});

describe("wording and keys", () => {
  it("never words confidence as a number", () => {
    expect(confidenceWording(0.82)).toBe("looksLike");
    expect(confidenceWording(0.55)).toBe("mightBe");
  });

  it("identifies a photo set regardless of order", () => {
    expect(suggestionKey(["b", "a"])).toBe(suggestionKey(["a", "b"]));
  });
});
