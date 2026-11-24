import { HttpResponse, http, type JsonBodyType } from "msw";
import { API } from "./msw";

/*
 * MSW handlers for the analytics endpoints (docs/api/analytics-notifications.md),
 * with small but realistic bodies. Every request is recorded so tests can
 * check the filters that were sent.
 */

const filters = {
  period: { start: "2026-10-26", end: "2026-11-24" },
  previous: { start: "2026-09-26", end: "2026-10-25" },
  category_id: null,
  ward_id: null,
  status: [],
};

const spark = (values: number[]) =>
  values.map((value, i) => ({
    bucket: `2026-11-${String(18 + i).padStart(2, "0")}`,
    value,
  }));

export const analyticsBodies = {
  overview: {
    filters,
    kpis: [
      {
        metric: "reports",
        unit: "count",
        value: 412,
        previous: 377,
        sparkline: spark([10, 14, 12, 18, 16, 15, 19]),
      },
      {
        metric: "issues",
        unit: "count",
        value: 301,
        previous: 300,
        sparkline: spark([8, 9, 10, 12, 9, 11, 13]),
      },
      {
        metric: "unique_reporters",
        unit: "count",
        value: 90,
        previous: 88,
        sparkline: spark([3, 4, 5, 3, 4, 5, 6]),
      },
      {
        metric: "resolution_time",
        unit: "hours",
        value: 72,
        previous: 96,
        sparkline: spark([80, 70, 75, 72, 68, 71, 72]),
      },
      {
        metric: "acknowledgement_time",
        unit: "hours",
        value: 5.5,
        previous: 5,
        sparkline: spark([5, 6, 5, 6, 5, 6, 5]),
      },
      {
        metric: "duplicate_rate",
        unit: "ratio",
        value: 0.24,
        previous: 0.2,
        sparkline: spark([0.2, 0.22, 0.25, 0.24, 0.23, 0.25, 0.24]),
      },
      {
        metric: "review_rate",
        unit: "ratio",
        value: 0.09,
        previous: null,
        sparkline: [],
      },
      {
        metric: "reopen_rate",
        unit: "ratio",
        value: 0.05,
        previous: 0.04,
        sparkline: spark([0.05, 0.04, 0.06, 0.05, 0.05, 0.05, 0.05]),
      },
      {
        metric: "sla_compliance",
        unit: "ratio",
        value: 0.85,
        previous: 0.8,
        sparkline: spark([0.8, 0.82, 0.85, 0.9, 0.84, 0.86, 0.85]),
      },
    ],
  },
  trend: {
    metrics: ["reports", "issues", "resolved"],
    interval: "day",
    filters,
    points: [
      { bucket: "2026-11-22", reports: 12, issues: 9, resolved: 4 },
      { bucket: "2026-11-23", reports: 15, issues: 11, resolved: 6 },
      { bucket: "2026-11-24", reports: 9, issues: 7, resolved: 8 },
    ],
  },
  byStatus: {
    metric: "issues_by_status",
    filters,
    total: 40,
    items: [
      { status: "reported", count: 10 },
      { status: "in_progress", count: 8 },
      { status: "resolved", count: 15 },
      { status: "closed", count: 5 },
      { status: "rejected", count: 2 },
    ],
  },
  byCategory: {
    metric: "issues_by_category",
    filters,
    items: [
      {
        category: {
          id: "cat-pothole",
          code: "pothole",
          name_i18n: { en: "Pothole", hi: "गड्ढा" },
          icon: "construction",
        },
        total: 25,
        statuses: [
          { status: "reported", count: 5 },
          { status: "resolved", count: 20 },
        ],
      },
    ],
  },
  byWard: {
    metrics: ["issues_by_ward", "resolution_time"],
    filters,
    items: [
      {
        ward: { id: "w1", code: "SYN-W01", name: "Ward 1" },
        issues: 30,
        open: 10,
        resolved: 18,
        median_resolution_hours: 60,
      },
      {
        ward: null,
        issues: 2,
        open: 2,
        resolved: 0,
        median_resolution_hours: null,
      },
    ],
  },
  resolution: {
    metric: "resolution_time",
    filters,
    count: 20,
    mean_hours: 80,
    median_hours: 60,
    p90_hours: 200,
    bins: [
      { lower_hours: 0, upper_hours: 24, count: 4 },
      { lower_hours: 24, upper_hours: 48, count: 5 },
      { lower_hours: 48, upper_hours: 72, count: 6 },
      { lower_hours: 72, upper_hours: null, count: 5 },
    ],
  },
  matching: {
    metrics: [
      "auto_link_rate",
      "review_rate",
      "duplicate_rate",
      "correction_rate",
    ],
    filters,
    decided_reports: 120,
    auto_link_rate: 0.17,
    review_rate: 0.09,
    duplicate_rate: 0.24,
    correction_rate: 0.05,
    feedback_count: 40,
  },
  hotspots: {
    metric: "hotspots",
    filters,
    resolution: 8,
    items: [
      {
        cell: "8861892e0bfffff",
        lng: 77.571,
        lat: 12.984,
        issues: 17,
        open: 6,
      },
    ],
  },
  activity: {
    metric: "report_activity",
    filters,
    items: [
      { weekday: 0, hour: 8, count: 12 },
      { weekday: 4, hour: 18, count: 7 },
    ],
  },
};

const routes: [string, JsonBodyType][] = [
  ["overview", analyticsBodies.overview],
  ["trend", analyticsBodies.trend],
  ["by-status", analyticsBodies.byStatus],
  ["by-category", analyticsBodies.byCategory],
  ["by-ward", analyticsBodies.byWard],
  ["resolution-times", analyticsBodies.resolution],
  ["matching-quality", analyticsBodies.matching],
  ["hotspots", analyticsBodies.hotspots],
  ["activity", analyticsBodies.activity],
];

export function analyticsHandlers(requests: URL[] = []) {
  return routes.map(([path, body]) =>
    http.get(`${API}/analytics/${path}`, ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json(body);
    }),
  );
}
