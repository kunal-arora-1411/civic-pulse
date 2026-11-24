import { apiRequest } from "../client";
import { type Paginated, paginated } from "../schemas";
import { type ReviewTask, reviewTaskSchema } from "../schemas-phase2";

export function listReviewTasks(
  params: { status?: "open" | "resolved"; limit?: number; offset?: number },
  signal?: AbortSignal,
): Promise<Paginated<ReviewTask>> {
  return apiRequest({
    path: "/review-tasks",
    query: { status: "open", ...params },
    schema: paginated(reviewTaskSchema),
    signal,
  });
}

export function getReviewTask(
  id: string,
  signal?: AbortSignal,
): Promise<ReviewTask> {
  return apiRequest({
    path: `/review-tasks/${encodeURIComponent(id)}`,
    schema: reviewTaskSchema,
    signal,
  });
}

export type ReviewAction =
  | { action: "link"; issue_id: string }
  | { action: "new_issue" };

/**
 * Settle a review task. A task someone else has already resolved comes
 * back as 409 `conflict`; the caller shows that rather than retrying.
 * The resolved task comes back with its report placed, so
 * `report.issue` is the issue it joined or the new one it started.
 */
export function resolveReviewTask(
  id: string,
  body: ReviewAction,
): Promise<ReviewTask> {
  return apiRequest({
    method: "POST",
    path: `/review-tasks/${encodeURIComponent(id)}/resolve`,
    body,
    schema: reviewTaskSchema,
  });
}

/** Mark an automatic (or reviewed) link as right or wrong (FR-035). */
export function sendMatchFeedback(
  matchDecisionId: string,
  body: { correct: boolean; note?: string },
): Promise<void> {
  return apiRequest({
    method: "POST",
    path: `/match-decisions/${encodeURIComponent(matchDecisionId)}/feedback`,
    body,
  });
}
