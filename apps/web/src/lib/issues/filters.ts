import {
  ISSUE_SORTS,
  ISSUE_STATUSES,
  type IssueFilterParams,
  type IssueListParams,
  type IssueSort,
  type IssueStatus,
} from "@/lib/api";

/*
 * Work queue and map filters, kept in the URL so a view can be shared
 * ("everything under review in ward 3 this week") and survives a reload
 * or the back button. Parsing is forgiving: unknown values are dropped
 * rather than breaking the page, since URLs get hand-edited and pasted.
 */

export type IssueFilters = {
  status: IssueStatus[];
  category: string[];
  ward: string[];
  /** Calendar dates, YYYY-MM-DD, inclusive. */
  from: string | null;
  to: string | null;
  q: string;
  sort: IssueSort;
  /** 1-based. */
  page: number;
};

export const DEFAULT_SORT: IssueSort = "-created_at";

export const EMPTY_FILTERS: IssueFilters = {
  status: [],
  category: [],
  ward: [],
  from: null,
  to: null,
  q: "",
  sort: DEFAULT_SORT,
  page: 1,
};

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const ID = /^[\w-]{1,64}$/;

function isDate(value: string | null): value is string {
  if (!value || !DATE.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().startsWith(value);
}

function unique<T>(values: T[]): T[] {
  return [...new Set(values)];
}

type ReadableParams = Pick<URLSearchParams, "get" | "getAll">;

export function parseIssueFilters(params: ReadableParams): IssueFilters {
  const status = unique(
    params
      .getAll("status")
      .filter((value): value is IssueStatus =>
        (ISSUE_STATUSES as readonly string[]).includes(value),
      ),
  );
  const ids = (key: string) =>
    unique(params.getAll(key).filter((value) => ID.test(value)));
  const sort = params.get("sort");
  const page = Number(params.get("page"));
  const from = params.get("from");
  const to = params.get("to");
  return {
    status,
    category: ids("category"),
    ward: ids("ward"),
    from: isDate(from) ? from : null,
    to: isDate(to) ? to : null,
    q: (params.get("q") ?? "").trim().slice(0, 200),
    sort: (ISSUE_SORTS as readonly string[]).includes(sort ?? "")
      ? (sort as IssueSort)
      : DEFAULT_SORT,
    page: Number.isInteger(page) && page > 1 ? page : 1,
  };
}

/**
 * The query string for a set of filters. Defaults are left out and keys
 * come in a fixed order, so the same view always has the same URL.
 */
export function serializeIssueFilters(
  filters: Partial<IssueFilters>,
): URLSearchParams {
  const value = { ...EMPTY_FILTERS, ...filters };
  const params = new URLSearchParams();
  if (value.q.trim()) params.set("q", value.q.trim());
  for (const status of unique(value.status)) params.append("status", status);
  for (const id of unique(value.category)) params.append("category", id);
  for (const id of unique(value.ward)) params.append("ward", id);
  if (value.from) params.set("from", value.from);
  if (value.to) params.set("to", value.to);
  if (value.sort !== DEFAULT_SORT) params.set("sort", value.sort);
  if (value.page > 1) params.set("page", String(value.page));
  return params;
}

/** Apply a change; any change other than paging goes back to page 1. */
export function updateFilters(
  current: IssueFilters,
  changes: Partial<IssueFilters>,
): IssueFilters {
  const next = { ...current, ...changes };
  if (!("page" in changes)) next.page = 1;
  return next;
}

export function activeFilterCount(filters: IssueFilters): number {
  return (
    filters.status.length +
    filters.category.length +
    filters.ward.length +
    (filters.from ? 1 : 0) +
    (filters.to ? 1 : 0) +
    (filters.q ? 1 : 0)
  );
}

export function isRangeInverted(filters: IssueFilters): boolean {
  return Boolean(filters.from && filters.to && filters.from > filters.to);
}

/** Filters in the API's terms, shared by the list and the GeoJSON feed. */
export function toFilterParams(filters: IssueFilters): IssueFilterParams {
  const inverted = isRangeInverted(filters);
  return {
    status: filters.status.length ? filters.status : undefined,
    category_id: filters.category.length ? filters.category : undefined,
    ward_id: filters.ward.length ? filters.ward : undefined,
    from: inverted ? undefined : (filters.from ?? undefined),
    to: inverted ? undefined : (filters.to ?? undefined),
    q: filters.q || undefined,
  };
}

export function toListParams(
  filters: IssueFilters,
  pageSize: number,
): IssueListParams {
  return {
    ...toFilterParams(filters),
    sort: filters.sort,
    limit: pageSize,
    offset: (filters.page - 1) * pageSize,
  };
}
