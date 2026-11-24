import type { z } from "zod";
import { apiRequest, type QueryValue } from "../client";
import {
  type Activity,
  type AnalyticsOverview,
  type AnalyticsTrend,
  activitySchema,
  type ByCategory,
  type ByStatus,
  type ByWard,
  byCategorySchema,
  byStatusSchema,
  byWardSchema,
  type Hotspots,
  hotspotsSchema,
  type MatchingQuality,
  matchingQualitySchema,
  overviewSchema,
  type ResolutionTimes,
  resolutionTimesSchema,
  trendSchema,
} from "../schemas-analytics";
import type { IssueStatus } from "../schemas-phase1";

/** The filters every analytics endpoint takes. Days are IST, inclusive. */
export type AnalyticsQuery = {
  from?: string;
  to?: string;
  category_id?: string;
  ward_id?: string;
  status?: IssueStatus[];
};

function get<T>(
  path: string,
  query: Record<string, QueryValue>,
  schema: z.ZodType<T>,
  signal?: AbortSignal,
): Promise<T> {
  return apiRequest({ path: `/analytics${path}`, query, schema, signal });
}

export const getAnalyticsOverview = (q: AnalyticsQuery, signal?: AbortSignal) =>
  get<AnalyticsOverview>("/overview", q, overviewSchema, signal);

export const getAnalyticsTrend = (
  q: AnalyticsQuery & { interval: "day" | "week" },
  signal?: AbortSignal,
) => get<AnalyticsTrend>("/trend", q, trendSchema, signal);

export const getAnalyticsByStatus = (q: AnalyticsQuery, signal?: AbortSignal) =>
  get<ByStatus>("/by-status", q, byStatusSchema, signal);

export const getAnalyticsByCategory = (
  q: AnalyticsQuery,
  signal?: AbortSignal,
) => get<ByCategory>("/by-category", q, byCategorySchema, signal);

export const getAnalyticsByWard = (q: AnalyticsQuery, signal?: AbortSignal) =>
  get<ByWard>("/by-ward", q, byWardSchema, signal);

export const getAnalyticsResolutionTimes = (
  q: AnalyticsQuery,
  signal?: AbortSignal,
) =>
  get<ResolutionTimes>("/resolution-times", q, resolutionTimesSchema, signal);

export const getAnalyticsMatchingQuality = (
  q: AnalyticsQuery,
  signal?: AbortSignal,
) =>
  get<MatchingQuality>("/matching-quality", q, matchingQualitySchema, signal);

export const getAnalyticsHotspots = (q: AnalyticsQuery, signal?: AbortSignal) =>
  get<Hotspots>("/hotspots", q, hotspotsSchema, signal);

export const getAnalyticsActivity = (q: AnalyticsQuery, signal?: AbortSignal) =>
  get<Activity>("/activity", q, activitySchema, signal);
