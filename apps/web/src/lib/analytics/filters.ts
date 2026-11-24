import {
  type AnalyticsQuery,
  ISSUE_STATUSES,
  type IssueStatus,
} from "@/lib/api";

/*
 * The analytics filters, kept in the URL so a view can be shared and
 * survives a reload. Pure functions, so they are tested without a router.
 */

export const RANGE_PRESETS = ["7d", "30d", "90d", "mtd", "custom"] as const;
export type RangePreset = (typeof RANGE_PRESETS)[number];
export type Interval = "day" | "week";

export type AnalyticsFilters = {
  range: RangePreset;
  /** Custom range only: IST days, inclusive. */
  from: string;
  to: string;
  category: string;
  ward: string;
  status: IssueStatus[];
  interval: Interval;
};

export const DEFAULT_FILTERS: AnalyticsFilters = {
  range: "30d",
  from: "",
  to: "",
  category: "",
  ward: "",
  status: [],
  interval: "day",
};

const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

/** Today's calendar day in India, whatever the browser's zone. */
export function todayIst(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

export function addDays(day: string, days: number): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function parseFilters(params: URLSearchParams): AnalyticsFilters {
  const range = params.get("range");
  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  const statuses = params
    .getAll("status")
    .filter((s): s is IssueStatus =>
      (ISSUE_STATUSES as readonly string[]).includes(s),
    );
  return {
    range: (RANGE_PRESETS as readonly string[]).includes(range ?? "")
      ? (range as RangePreset)
      : DEFAULT_FILTERS.range,
    from: DAY_RE.test(from) ? from : "",
    to: DAY_RE.test(to) ? to : "",
    category: params.get("category") ?? "",
    ward: params.get("ward") ?? "",
    status: statuses,
    interval: params.get("interval") === "week" ? "week" : "day",
  };
}

/** Only what differs from the defaults, in a stable order. */
export function serializeFilters(filters: AnalyticsFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.range !== DEFAULT_FILTERS.range)
    params.set("range", filters.range);
  if (filters.range === "custom") {
    if (filters.from) params.set("from", filters.from);
    if (filters.to) params.set("to", filters.to);
  }
  if (filters.category) params.set("category", filters.category);
  if (filters.ward) params.set("ward", filters.ward);
  for (const status of filters.status) params.append("status", status);
  if (filters.interval !== "day") params.set("interval", filters.interval);
  return params;
}

/** The IST days a preset covers, ending today. */
export function resolvePeriod(
  filters: AnalyticsFilters,
  today: string = todayIst(),
): { from: string; to: string } {
  switch (filters.range) {
    case "7d":
      return { from: addDays(today, -6), to: today };
    case "90d":
      return { from: addDays(today, -89), to: today };
    case "mtd":
      return { from: `${today.slice(0, 8)}01`, to: today };
    case "custom":
      return {
        from: filters.from || addDays(filters.to || today, -29),
        to: filters.to || today,
      };
    default:
      return { from: addDays(today, -29), to: today };
  }
}

export function isRangeInvalid(filters: AnalyticsFilters): boolean {
  return Boolean(
    filters.range === "custom" &&
      filters.from &&
      filters.to &&
      filters.from > filters.to,
  );
}

export function toQuery(
  filters: AnalyticsFilters,
  today?: string,
): AnalyticsQuery {
  const { from, to } = resolvePeriod(filters, today);
  return {
    from,
    to,
    category_id: filters.category || undefined,
    ward_id: filters.ward || undefined,
    status: filters.status.length ? filters.status : undefined,
  };
}

export function activeFilterCount(filters: AnalyticsFilters): number {
  return (
    (filters.range !== DEFAULT_FILTERS.range ? 1 : 0) +
    (filters.category ? 1 : 0) +
    (filters.ward ? 1 : 0) +
    (filters.status.length ? 1 : 0)
  );
}
