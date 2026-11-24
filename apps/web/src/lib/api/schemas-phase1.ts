import { z } from "zod";
import { jurisdictionSchema, lngLatSchema } from "./schemas";
import {
  matchDecisionSchema,
  matchingStatusSchema,
  priorityBandSchema,
  prioritySchema,
  reportMatchSchema,
  severitySchema,
} from "./schemas-ai";

/*
 * Response schemas for the Phase 1 contract (docs/api/phase-1-contract.md):
 * categories, media, geocoding, reports and civic issues. Same rules as
 * schemas.ts: hand-written until orval generates them, and exported names
 * are what feature code depends on.
 */

/** `{ "en": "Pothole", "hi": "गड्ढा" }`. Pick a locale with `localized()`. */
export const i18nTextSchema = z.record(z.string(), z.string());
export type I18nText = z.infer<typeof i18nTextSchema>;

// ---------------------------------------------------------------- categories

export const CATEGORY_FIELD_TYPES = [
  "text",
  "number",
  "select",
  "boolean",
] as const;
export type CategoryFieldType = (typeof CATEGORY_FIELD_TYPES)[number];

export const categoryFieldOptionSchema = z.object({
  value: z.string(),
  label_i18n: i18nTextSchema,
});
export type CategoryFieldOption = z.infer<typeof categoryFieldOptionSchema>;

export const categoryFieldSchema = z.object({
  key: z.string(),
  type: z.enum(CATEGORY_FIELD_TYPES),
  required: z.boolean().default(false),
  label_i18n: i18nTextSchema,
  options: z.array(categoryFieldOptionSchema).nullish(),
});
export type CategoryField = z.infer<typeof categoryFieldSchema>;

export const categorySchema = z.object({
  id: z.string(),
  code: z.string(),
  parent_id: z.string().nullish(),
  name_i18n: i18nTextSchema,
  description_i18n: i18nTextSchema.nullish(),
  icon: z.string().nullish(),
  evidence: z.object({
    min_photos: z.number().int().min(0),
    max_photos: z.number().int().min(0),
  }),
  fields: z.array(categoryFieldSchema).default([]),
  default_department_id: z.string().nullish(),
  dedup: z.object({ radius_m: z.number(), window_days: z.number() }).nullish(),
  sort_order: z.number(),
  is_active: z.boolean(),
});
export type Category = z.infer<typeof categorySchema>;

/** The category as embedded in reports and issues. */
export const categorySummarySchema = z.object({
  id: z.string(),
  code: z.string(),
  name_i18n: i18nTextSchema,
  icon: z.string().nullish(),
});
export type CategorySummary = z.infer<typeof categorySummarySchema>;

// --------------------------------------------------------------------- media

export const ALLOWED_UPLOAD_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
] as const;
export type UploadContentType = (typeof ALLOWED_UPLOAD_TYPES)[number];

export const uploadTicketSchema = z.object({
  upload_id: z.string(),
  method: z.string().default("PUT"),
  url: z.string(),
  headers: z.record(z.string(), z.string()).default({}),
  expires_in: z.number(),
  max_size_bytes: z.number(),
});
export type UploadTicket = z.infer<typeof uploadTicketSchema>;

export const MEDIA_STATUSES = ["processing", "ready", "failed"] as const;
export const mediaStatusSchema = z.enum(MEDIA_STATUSES);

/** Returned by `POST /media/uploads/{id}/complete`. */
export const mediaAssetSchema = z.object({
  id: z.string(),
  status: mediaStatusSchema,
  content_type: z.string(),
  width: z.number().nullish(),
  height: z.number().nullish(),
  variants: z
    .object({ thumb: z.string().nullish(), display: z.string().nullish() })
    .partial()
    .nullish(),
  captured_at: z.string().nullish(),
});
export type MediaAsset = z.infer<typeof mediaAssetSchema>;

/** Media as embedded in report and issue responses. */
export const mediaSchema = z.object({
  id: z.string(),
  status: mediaStatusSchema,
  width: z.number().nullish(),
  height: z.number().nullish(),
  thumb_url: z.string().nullish(),
  display_url: z.string().nullish(),
  original_url: z.string().nullish(),
  captured_at: z.string().nullish(),
});
export type Media = z.infer<typeof mediaSchema>;

// ----------------------------------------------------------------------- geo

export const wardRefSchema = z.object({
  id: z.string(),
  name: z.string(),
  code: z.string().nullish(),
});
export type WardRef = z.infer<typeof wardRefSchema>;

export const reverseGeocodeSchema = z.object({
  address_text: z.string().nullable(),
  in_jurisdiction: z.boolean(),
  ward: wardRefSchema.nullish(),
  zone: z.object({ id: z.string(), name: z.string() }).nullish(),
});
export type ReverseGeocode = z.infer<typeof reverseGeocodeSchema>;

export const LOCATION_SOURCES = ["gps", "pin", "manual"] as const;
export type LocationSource = (typeof LOCATION_SOURCES)[number];

export const reportLocationSchema = z.object({
  lat: z.number(),
  lng: z.number(),
  accuracy_m: z.number().nullish(),
  source: z.enum(LOCATION_SOURCES),
});
export type ReportLocation = z.infer<typeof reportLocationSchema>;

// -------------------------------------------------------------------- issues

/** PRD FR-052, in lifecycle order. */
export const ISSUE_STATUSES = [
  "reported",
  "under_review",
  "verified",
  "assigned",
  "in_progress",
  "pending_verification",
  "resolved",
  "rejected",
  "closed",
  "reopened",
] as const;
export const issueStatusSchema = z.enum(ISSUE_STATUSES);
export type IssueStatus = z.infer<typeof issueStatusSchema>;

export const publicTimelineEventSchema = z.object({
  at: z.string(),
  type: z.string(),
  from_status: issueStatusSchema.nullish(),
  to_status: issueStatusSchema.nullish(),
  public_note: z.string().nullish(),
});
export type PublicTimelineEvent = z.infer<typeof publicTimelineEventSchema>;

const reportCoreSchema = z.object({
  id: z.string(),
  reference: z.string(),
  created_at: z.string(),
  category: categorySummarySchema,
  description: z
    .string()
    .nullish()
    .transform((v) => v ?? ""),
  details: z.record(z.string(), z.unknown()).nullish().default({}),
  location: reportLocationSchema,
  address_text: z.string().nullish(),
  ward: wardRefSchema.nullish(),
  media: z.array(mediaSchema).default([]),
  status: z.string(),
  /** Tells the owner and staff shapes apart. */
  view: z.enum(["owner", "staff"]).nullish(),
  /**
   * Phase 2: where duplicate matching has got to. Absent from Phase 1
   * responses, where every report had its own issue from the start.
   */
  matching_status: matchingStatusSchema.nullish(),
});

const reporterSchema = z
  .object({ id: z.string(), display_name: z.string().nullable() })
  .nullish();

/** `GET /reports/{id}` and the `POST /reports` response (owner view). */
export const reportSchema = reportCoreSchema.extend({
  /** Null while matching is pending or waiting for a reviewer. */
  issue: z
    .object({
      id: z.string(),
      reference: z.string(),
      status: issueStatusSchema,
      report_count: z.number().nullish(),
      unique_reporter_count: z.number().nullish(),
      timeline: z.array(publicTimelineEventSchema).default([]),
    })
    .nullable(),
  /** Present in the staff view only. */
  reporter: reporterSchema,
  /** Staff view only: the decision that placed the report. */
  match: reportMatchSchema.nullish(),
});
export type Report = z.infer<typeof reportSchema>;

/** A report inside an issue detail or a review task (staff view). */
export const staffReportSchema = reportCoreSchema.extend({
  reporter: reporterSchema,
  match: reportMatchSchema.nullish(),
  /** Issue detail only: every candidate considered for this report. */
  match_decisions: z.array(matchDecisionSchema).default([]),
});
export type StaffReport = z.infer<typeof staffReportSchema>;

export const myReportSchema = z.object({
  id: z.string(),
  reference: z.string(),
  created_at: z.string(),
  category: categorySummarySchema,
  thumb_url: z.string().nullish(),
  address_text: z.string().nullish(),
  /** Null while matching is pending or waiting for a reviewer. */
  issue: z
    .object({ reference: z.string(), status: issueStatusSchema })
    .nullable(),
  matching_status: matchingStatusSchema.nullish(),
});
export type MyReport = z.infer<typeof myReportSchema>;

export const issueListItemSchema = z.object({
  id: z.string(),
  reference: z.string(),
  status: issueStatusSchema,
  category: categorySummarySchema,
  location: z.object({ lat: z.number(), lng: z.number() }),
  address_text: z.string().nullish(),
  ward: wardRefSchema.nullish(),
  report_count: z.number(),
  unique_reporter_count: z.number(),
  severity: severitySchema.nullish(),
  priority: prioritySchema.nullish(),
  thumb_url: z.string().nullish(),
  created_at: z.string(),
  updated_at: z.string(),
  version: z.number(),
});
export type IssueListItem = z.infer<typeof issueListItemSchema>;

export const issueTimelineEventSchema = z.object({
  id: z.string(),
  at: z.string(),
  type: z.string(),
  from_status: issueStatusSchema.nullish(),
  to_status: issueStatusSchema.nullish(),
  reason: z.string().nullish(),
  public_note: z.string().nullish(),
  visibility: z.enum(["public", "internal"]),
  actor: z
    .object({ id: z.string(), display_name: z.string().nullable() })
    .nullish(),
});
export type IssueTimelineEvent = z.infer<typeof issueTimelineEventSchema>;

export const allowedTransitionSchema = z.object({
  to_status: issueStatusSchema,
  requires_reason: z.boolean(),
});
export type AllowedTransition = z.infer<typeof allowedTransitionSchema>;

export const issueRefSchema = z.object({
  id: z.string(),
  reference: z.string(),
});
export type IssueRef = z.infer<typeof issueRefSchema>;

export const relatedIssueSchema = z.object({
  issue: issueListItemSchema,
  note: z.string().nullish(),
});
export type RelatedIssue = z.infer<typeof relatedIssueSchema>;

export const issueDetailSchema = issueListItemSchema.extend({
  reports: z.array(staffReportSchema).default([]),
  timeline: z.array(issueTimelineEventSchema).default([]),
  allowed_transitions: z.array(allowedTransitionSchema).default([]),
  related: z.array(relatedIssueSchema).default([]),
});
export type IssueDetail = z.infer<typeof issueDetailSchema>;

/**
 * `GET /issues/{id}` for an issue that was merged away. The contract
 * returns 200 with `merged_into` so the client can redirect; only the
 * fields needed for that are relied on.
 */
export const mergedIssueSchema = z.object({
  id: z.string(),
  reference: z.string(),
  merged_into: issueRefSchema,
});
export type MergedIssue = z.infer<typeof mergedIssueSchema>;

export const issueFeatureSchema = z.object({
  type: z.literal("Feature"),
  geometry: z.object({
    type: z.literal("Point"),
    coordinates: lngLatSchema,
  }),
  properties: z.object({
    id: z.string(),
    reference: z.string(),
    status: issueStatusSchema,
    category_code: z.string(),
    report_count: z.number(),
    /** Phase 2: the effective band, so the map can style by priority. */
    priority_band: priorityBandSchema.nullish(),
  }),
});
export type IssueFeature = z.infer<typeof issueFeatureSchema>;

export const issueFeatureCollectionSchema = z.object({
  type: z.literal("FeatureCollection"),
  features: z.array(issueFeatureSchema),
  truncated: z.boolean().default(false),
});
export type IssueFeatureCollection = z.infer<
  typeof issueFeatureCollectionSchema
>;

// -------------------------------------------------------------- jurisdictions

const position = z.array(z.number()).min(2);

export const multiPolygonSchema = z.object({
  type: z.literal("MultiPolygon"),
  coordinates: z.array(z.array(z.array(position))),
});
export type MultiPolygon = z.infer<typeof multiPolygonSchema>;

export const jurisdictionWithGeometrySchema = jurisdictionSchema.extend({
  geometry: multiPolygonSchema.nullish(),
});
export type JurisdictionWithGeometry = z.infer<
  typeof jurisdictionWithGeometrySchema
>;
