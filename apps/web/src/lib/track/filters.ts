import {
  ISSUE_STATUSES,
  type IssueStatus,
  type PublicIssueFilters,
  type PublicSort,
} from "@/lib/api";

/** The public tracker never lists rejected issues. */
export const PUBLIC_STATUSES = ISSUE_STATUSES.filter(
  (status) => status !== "rejected",
);

/** Everything still waiting for a fix. */
export const OPEN_STATUSES: IssueStatus[] = PUBLIC_STATUSES.filter(
  (status) => status !== "resolved" && status !== "closed",
);

/** "" = all, "open" = every open status, otherwise one status. */
export type StatusChoice = "" | "open" | IssueStatus;

export type TrackFilters = {
  status: StatusChoice;
  category_id: string;
  ward_id: string;
  sort: PublicSort;
};

export const DEFAULT_TRACK_FILTERS: TrackFilters = {
  status: "",
  category_id: "",
  ward_id: "",
  sort: "-created_at",
};

/** The query the public endpoints take; empty choices are left out. */
export function toQuery(filters: TrackFilters): PublicIssueFilters {
  const status =
    filters.status === ""
      ? undefined
      : filters.status === "open"
        ? OPEN_STATUSES
        : [filters.status];
  return {
    status,
    category_id: filters.category_id || undefined,
    ward_id: filters.ward_id || undefined,
  };
}

export function isFiltered(filters: TrackFilters): boolean {
  return (
    filters.status !== "" ||
    filters.category_id !== "" ||
    filters.ward_id !== ""
  );
}
