import type { MatchingStatus, Report } from "@/lib/api";

/*
 * After a report is sent, the API checks it against existing issues in
 * the background (Phase 2 contract D.1). Until that's done the report has
 * no issue, and the citizen sees "Checking for similar reports". The
 * pages that show a report poll for the outcome, quickly at first and
 * then less and less often.
 */

/** First wait, growth per poll and the longest wait between polls. */
export const MATCHING_POLL = {
  initialMs: 1_000,
  factor: 1.5,
  maxMs: 15_000,
  /** About three minutes in all; after that the page says it's slow. */
  maxPolls: 20,
} as const;

export type MatchingView =
  /** Matching is running. */
  | { state: "pending" }
  /** A member of staff is deciding (a review task is open). */
  | { state: "review" }
  | {
      state: "linked";
      reference: string;
      /** Distinct people who reported the issue, when the API says. */
      people: number | null;
    }
  | { state: "new_issue"; reference: string }
  /** A Phase 1 report, placed on its own issue when it was created. */
  | { state: "placed"; reference: string };

/** What to tell the citizen about where their report ended up. */
export function matchingView(
  report: Pick<Report, "matching_status" | "issue">,
): MatchingView {
  const issue = report.issue;
  const status: MatchingStatus | null | undefined = report.matching_status;
  if (!issue)
    return status === "review" ? { state: "review" } : { state: "pending" };
  if (status === "linked") {
    return {
      state: "linked",
      reference: issue.reference,
      people: issue.unique_reporter_count ?? issue.report_count ?? null,
    };
  }
  if (status === "new_issue") {
    return { state: "new_issue", reference: issue.reference };
  }
  return { state: "placed", reference: issue.reference };
}

export function isAwaitingMatch(
  report: Pick<Report, "matching_status" | "issue"> | undefined,
): boolean {
  if (!report) return false;
  const state = matchingView(report).state;
  return state === "pending" || state === "review";
}

/**
 * A React Query `refetchInterval` with backoff: 1 s, 1.5 s, 2.25 s … up to
 * 15 s between polls while the report waits for matching, and stop after
 * `maxPolls`. A review can take a while, so it follows the same schedule
 * rather than polling hard.
 */
export function matchingRefetchInterval(
  report: Pick<Report, "matching_status" | "issue"> | undefined,
  pollsSoFar: number,
): number | false {
  if (!isAwaitingMatch(report)) return false;
  if (pollsSoFar >= MATCHING_POLL.maxPolls) return false;
  return Math.min(
    MATCHING_POLL.maxMs,
    Math.round(MATCHING_POLL.initialMs * MATCHING_POLL.factor ** pollsSoFar),
  );
}

/** Matching normally takes seconds; past this, say it's running late. */
export const MATCHING_SLOW_MS = 3 * 60_000;

/**
 * True when automatic matching has taken unusually long, measured from
 * when the report was sent, so a page opened hours later says the same
 * thing. A report waiting for a member of staff (review) is never "late":
 * that can take hours, and the page says who it is waiting for.
 */
export function matchingIsSlow(
  report: Pick<Report, "matching_status" | "issue" | "created_at"> | undefined,
  now: Date,
): boolean {
  if (!report || matchingView(report).state !== "pending") return false;
  return now.getTime() - Date.parse(report.created_at) > MATCHING_SLOW_MS;
}

/** Combine two refetch intervals: the sooner one wins. */
export function soonest(...intervals: (number | false)[]): number | false {
  const active = intervals.filter((value): value is number => value !== false);
  return active.length ? Math.min(...active) : false;
}
