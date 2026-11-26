import { describe, expect, it } from "vitest";
import { makeReport } from "@/test/fixtures";
import {
  MATCHING_POLL,
  matchingIsSlow,
  matchingRefetchInterval,
  matchingView,
  soonest,
} from "./matching";

const pending = makeReport({ matching_status: "pending", issue: null });
const issue = makeReport().issue;
if (!issue) throw new Error("fixture has an issue");

describe("matchingView", () => {
  it("says checking while there's no issue, and staff review when a task is open", () => {
    expect(matchingView(pending)).toEqual({ state: "pending" });
    expect(
      matchingView(makeReport({ matching_status: "review", issue: null })),
    ).toEqual({ state: "review" });
  });

  it("counts people, not reports, for a linked report", () => {
    expect(
      matchingView(
        makeReport({
          matching_status: "linked",
          issue: { ...issue, report_count: 5, unique_reporter_count: 3 },
        }),
      ),
    ).toEqual({ state: "linked", reference: "CP-26-000123", people: 3 });
  });

  it("tells a new issue from a Phase 1 report that always had one", () => {
    expect(
      matchingView(makeReport({ matching_status: "new_issue" })).state,
    ).toBe("new_issue");
    expect(matchingView(makeReport()).state).toBe("placed");
  });
});

describe("matchingRefetchInterval", () => {
  it("backs off from a second up to fifteen seconds, then stops", () => {
    const waits = Array.from({ length: MATCHING_POLL.maxPolls + 1 }, (_, n) =>
      matchingRefetchInterval(pending, n),
    );
    expect(waits.slice(0, 4)).toEqual([1000, 1500, 2250, 3375]);
    expect(Math.max(...waits.filter((w): w is number => w !== false))).toBe(
      15_000,
    );
    expect(waits.at(-1)).toBe(false);
  });

  it("doesn't poll once the report has an issue", () => {
    expect(
      matchingRefetchInterval(makeReport({ matching_status: "linked" }), 0),
    ).toBe(false);
  });

  it("combines with the photo-processing interval, sooner first", () => {
    expect(soonest(3000, 1500)).toBe(1500);
    expect(soonest(false, 1500)).toBe(1500);
    expect(soonest(false, false)).toBe(false);
  });
});

describe("matchingIsSlow", () => {
  it("is slow three minutes after sending if still unplaced", () => {
    const sent = { ...pending, created_at: "2026-11-24T08:00:00Z" };
    expect(matchingIsSlow(sent, new Date("2026-11-24T08:02:00Z"))).toBe(false);
    expect(matchingIsSlow(sent, new Date("2026-11-24T08:04:00Z"))).toBe(true);
    expect(
      matchingIsSlow(
        { ...makeReport(), created_at: "2026-11-24T08:00:00Z" },
        new Date("2026-11-25T08:00:00Z"),
      ),
    ).toBe(false);
  });

  it("is never slow while a member of staff is reviewing it", () => {
    const inReview = makeReport({
      matching_status: "review",
      issue: null,
      created_at: "2026-11-24T08:00:00Z",
    });
    expect(matchingIsSlow(inReview, new Date("2026-11-25T08:00:00Z"))).toBe(
      false,
    );
  });
});
