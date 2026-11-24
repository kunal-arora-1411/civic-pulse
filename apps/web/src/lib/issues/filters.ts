import {
  ISSUE_SORTS,
  ISSUE_STATUSES,
  type IssueFilterParams,
  type IssueListParams,
  type IssueSort,
  type IssueStatus,
  PRIORITY_BANDS,
  type PriorityBand,
  SEVERITY_LEVELS,
  type SeverityLevel,
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
  severity: SeverityLevel[];
  /** Effective priority band; `band` in the URL. */
  band: PriorityBand[];
  /** Calendar dates, YYYY-MM-DD, inclusive. */
  from: string | null;
  to: string | null;
  q: string;
  sort: IssueSort;
  /** 1-based. */
  page: number;
};

/** Most urgent first: what staff should look at next is at the top. */
export const DEFAULT_SORT: IssueSort = "-priority";

export const EMPTY_FILTERS: IssueFilters = {
  status: [],
  category: [],
  ward: [],
  severity: [],
  band: [],
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

/** Repeated values of `key` that belong to `allowed`, in URL order. */
function oneOf<T extends string>(
  params: ReadableParams,
  key: string,
  allowed: readonly T[],
): T[] {
  return unique(
    params
      .getAll(key)
      .filter((value): value is T =>
        (allowed as readonly string[]).includes(value),
      ),
  );
}

export function parseIssueFilters(params: ReadableParams): IssueFilters {
  const status = oneOf(params, "status", ISSUE_STATUSES);
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
    severity: oneOf(params, "severity", SEVERITY_LEVELS),
    band: oneOf(params, "band", PRIORITY_BANDS),
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
  // Undefined means "not set": it mustn't override a default and end up
  // in the URL as the string "undefined".
  const defined = Object.fromEntries(
    Object.entries(filters).filter(([, item]) => item !== undefined),
  ) as Partial<IssueFilters>;
  const value = { ...EMPTY_FILTERS, ...defined };
  const params = new URLSearchParams();
  if (value.q.trim()) params.set("q", value.q.trim());
  for (const status of unique(value.status)) params.append("status", status);
  for (const id of unique(value.category)) params.append("category", id);
  for (const id of unique(value.ward)) params.append("ward", id);
  for (const level of unique(value.severity)) params.append("severity", level);
  for (const band of unique(value.band)) params.append("band", band);
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
    filters.severity.length +
    filters.band.length +
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
    severity: filters.severity.length ? filters.severity : undefined,
    priority_band: filters.band.length ? filters.band : undefined,
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
