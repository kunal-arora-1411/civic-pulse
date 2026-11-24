import { z } from "zod";
import { i18nTextSchema, issueStatusSchema } from "./schemas-phase1";

/*
 * Analytics (docs/api/analytics-notifications.md). Every figure names its
 * docs/metrics.md entry in `metric` / `metrics`.
 */

const day = z.string(); // YYYY-MM-DD, an IST calendar day

export const analyticsFiltersSchema = z.object({
  period: z.object({ start: day, end: day }),
  previous: z.object({ start: day, end: day }),
  category_id: z.string().nullable(),
  ward_id: z.string().nullable(),
  status: z.array(issueStatusSchema),
});

export const kpiSchema = z.object({
  metric: z.string(),
  unit: z.enum(["count", "hours", "ratio"]),
  value: z.number().nullable(),
  previous: z.number().nullable(),
  sparkline: z.array(z.object({ bucket: day, value: z.number().nullable() })),
});
export type Kpi = z.infer<typeof kpiSchema>;

export const overviewSchema = z.object({
  filters: analyticsFiltersSchema,
  kpis: z.array(kpiSchema),
});
export type AnalyticsOverview = z.infer<typeof overviewSchema>;

export const trendSchema = z.object({
  metrics: z.array(z.string()),
  interval: z.enum(["day", "week"]),
  filters: analyticsFiltersSchema,
  points: z.array(
    z.object({
      bucket: day,
      reports: z.number(),
      issues: z.number(),
      resolved: z.number(),
    }),
  ),
});
export type AnalyticsTrend = z.infer<typeof trendSchema>;

const statusCountSchema = z.object({
  status: issueStatusSchema,
  count: z.number(),
});
export type StatusCount = z.infer<typeof statusCountSchema>;

export const byStatusSchema = z.object({
  metric: z.string(),
  filters: analyticsFiltersSchema,
  total: z.number(),
  items: z.array(statusCountSchema),
});
export type ByStatus = z.infer<typeof byStatusSchema>;

export const byCategorySchema = z.object({
  metric: z.string(),
  filters: analyticsFiltersSchema,
  items: z.array(
    z.object({
      category: z.object({
        id: z.string(),
        code: z.string(),
        name_i18n: i18nTextSchema,
        icon: z.string(),
      }),
      total: z.number(),
      statuses: z.array(statusCountSchema),
    }),
  ),
});
export type ByCategory = z.infer<typeof byCategorySchema>;

export const byWardSchema = z.object({
  metrics: z.array(z.string()),
  filters: analyticsFiltersSchema,
  items: z.array(
    z.object({
      ward: z
        .object({ id: z.string(), code: z.string(), name: z.string() })
        .nullable(),
      issues: z.number(),
      open: z.number(),
      resolved: z.number(),
      median_resolution_hours: z.number().nullable(),
    }),
  ),
});
export type ByWard = z.infer<typeof byWardSchema>;

export const resolutionTimesSchema = z.object({
  metric: z.string(),
  filters: analyticsFiltersSchema,
  count: z.number(),
  mean_hours: z.number().nullable(),
  median_hours: z.number().nullable(),
  p90_hours: z.number().nullable(),
  bins: z.array(
    z.object({
      lower_hours: z.number(),
      upper_hours: z.number().nullable(),
      count: z.number(),
    }),
  ),
});
export type ResolutionTimes = z.infer<typeof resolutionTimesSchema>;

export const matchingQualitySchema = z.object({
  metrics: z.array(z.string()),
  filters: analyticsFiltersSchema,
  decided_reports: z.number(),
  auto_link_rate: z.number().nullable(),
  review_rate: z.number().nullable(),
  duplicate_rate: z.number().nullable(),
  correction_rate: z.number().nullable(),
  feedback_count: z.number(),
});
export type MatchingQuality = z.infer<typeof matchingQualitySchema>;

export const hotspotsSchema = z.object({
  metric: z.string(),
  filters: analyticsFiltersSchema,
  resolution: z.number(),
  items: z.array(
    z.object({
      cell: z.string(),
      lng: z.number(),
      lat: z.number(),
      issues: z.number(),
      open: z.number(),
    }),
  ),
});
export type Hotspots = z.infer<typeof hotspotsSchema>;
export type Hotspot = Hotspots["items"][number];

export const activitySchema = z.object({
  metric: z.string(),
  filters: analyticsFiltersSchema,
  items: z.array(
    z.object({ weekday: z.number(), hour: z.number(), count: z.number() }),
  ),
});
export type Activity = z.infer<typeof activitySchema>;
