"use client";

import { useQuery } from "@tanstack/react-query";
import { listReviewTasks } from "@/lib/api";
import { hasPermission } from "@/lib/auth/access";
import { useSession } from "@/lib/auth/use-session";

export const REVIEW_COUNT_KEY = ["review-tasks", "open-count"] as const;

/**
 * How many reports are waiting for a duplicate decision, for the nav
 * badge and the work queue's notice. Only asked for when the user can
 * triage, refreshed every minute, and 0 rather than an error state when
 * the request fails: a badge isn't worth an alert.
 */
export function useOpenReviewCount(): number {
  const { user } = useSession();
  const enabled = hasPermission(user, "issue:triage");
  const query = useQuery({
    queryKey: REVIEW_COUNT_KEY,
    queryFn: ({ signal }) =>
      listReviewTasks({ status: "open", limit: 1 }, signal),
    enabled,
    refetchInterval: 60_000,
    select: (page) => page.total,
  });
  return enabled ? (query.data ?? 0) : 0;
}
