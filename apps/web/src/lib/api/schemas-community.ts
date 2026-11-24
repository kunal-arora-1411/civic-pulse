import { z } from "zod";
import { lngLatSchema, paginated } from "./schemas";
import {
  categorySummarySchema,
  issueFeatureSchema,
  issueStatusSchema,
  publicTimelineEventSchema,
  wardRefSchema,
} from "./schemas-phase1";

/*
 * Community support and public resolution tracking
 * (docs/api/community-public.md).
 */

/** GET/POST/DELETE /issues/{id}/support */
export const supportStateSchema = z.object({
  issue_id: z.string(),
  support_count: z.number(),
  supported: z.boolean(),
});
export type SupportState = z.infer<typeof supportStateSchema>;

/** A public photo: face-blurred copies only. */
export const publicPhotoSchema = z.object({
  thumb_url: z.string(),
  display_url: z.string(),
});
export type PublicPhoto = z.infer<typeof publicPhotoSchema>;

export const publicIssueItemSchema = z.object({
  id: z.string(),
  reference: z.string(),
  status: issueStatusSchema,
  category: categorySummarySchema,
  ward: wardRefSchema.nullish(),
  /** The centre of the issue's coarse H3 cell, never the exact spot. */
  location: z.object({
    lat: z.number(),
    lng: z.number(),
    precision_m: z.number(),
  }),
  report_count: z.number(),
  support_count: z.number(),
  thumb_url: z.string().nullish(),
  created_at: z.string(),
  updated_at: z.string(),
  resolved_at: z.string().nullish(),
  age_days: z.number(),
});
export type PublicIssueItem = z.infer<typeof publicIssueItemSchema>;

export const publicIssuePageSchema = paginated(publicIssueItemSchema);

export const publicIssueDetailSchema = publicIssueItemSchema.extend({
  timeline: z.array(publicTimelineEventSchema).default([]),
  before_photos: z.array(publicPhotoSchema).default([]),
  after_photos: z.array(publicPhotoSchema).default([]),
  /** The reference this issue was merged into. */
  merged_into: z.string().nullish(),
  merged_into_id: z.string().nullish(),
});
export type PublicIssueDetail = z.infer<typeof publicIssueDetailSchema>;

/** Same shape as the staff map's features, plus the support count. */
export const publicFeatureSchema = issueFeatureSchema.extend({
  geometry: z.object({ type: z.literal("Point"), coordinates: lngLatSchema }),
  properties: issueFeatureSchema.shape.properties.extend({
    support_count: z.number().default(0),
  }),
});
export type PublicFeature = z.infer<typeof publicFeatureSchema>;

export const publicFeatureCollectionSchema = z.object({
  type: z.literal("FeatureCollection"),
  features: z.array(publicFeatureSchema),
  truncated: z.boolean().default(false),
});
export type PublicFeatureCollection = z.infer<
  typeof publicFeatureCollectionSchema
>;

export const wardScoreSchema = z.object({
  ward: wardRefSchema,
  open_count: z.number(),
  resolved_count: z.number(),
  median_resolution_days: z.number().nullable(),
});
export type WardScore = z.infer<typeof wardScoreSchema>;

export const scorecardSchema = z.object({ wards: z.array(wardScoreSchema) });
export type Scorecard = z.infer<typeof scorecardSchema>;

export const PUBLIC_SORTS = [
  "-created_at",
  "created_at",
  "-updated_at",
  "-support_count",
  "-report_count",
] as const;
export type PublicSort = (typeof PUBLIC_SORTS)[number];
