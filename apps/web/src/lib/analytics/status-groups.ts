import type { IssueStatus, StatusCount } from "@/lib/api";

/*
 * Ten statuses are too many to tell apart by colour, so the charts fold
 * them into four stages of the lifecycle (each chart's table view keeps
 * the exact statuses). The slots are the chart palette in fixed order and
 * follow the stage, never its rank, so filtering never repaints a stage.
 */
export const STATUS_GROUPS = [
  {
    key: "new",
    color: "var(--viz-1)",
    statuses: ["reported", "under_review", "verified"],
  },
  {
    key: "inWork",
    color: "var(--viz-2)",
    statuses: ["assigned", "in_progress", "pending_verification", "reopened"],
  },
  { key: "done", color: "var(--viz-3)", statuses: ["resolved", "closed"] },
  { key: "rejected", color: "var(--viz-4)", statuses: ["rejected"] },
] as const satisfies readonly {
  key: string;
  color: string;
  statuses: readonly IssueStatus[];
}[];

export type StatusGroupKey = (typeof STATUS_GROUPS)[number]["key"];

export function groupStatuses(
  items: readonly StatusCount[],
): Record<StatusGroupKey, number> {
  const totals = { new: 0, inWork: 0, done: 0, rejected: 0 };
  for (const item of items) {
    const group = STATUS_GROUPS.find((g) =>
      (g.statuses as readonly IssueStatus[]).includes(item.status),
    );
    if (group) totals[group.key] += item.count;
  }
  return totals;
}
