import {
  CategoryOut,
  CategoryRef,
  FieldOption,
  CategoryField as GenCategoryField,
  IssueStatus as GenIssueStatus,
  LocationSource as GenLocationSource,
  LocationOut,
  MediaAssetOut,
  MediaOut,
  MediaStatus,
  MediaVariants,
  ReverseGeocodeOut,
  UploadCreated,
  Visibility,
} from "@civicpulse/api-client";
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
import { slaStateSchema } from "./schemas-sla";
import { expectType, type Same } from "./type-checks";

/*
 * Response schemas for the Phase 1 contract (docs/api/phase-1-contract.md):
 * categories, media, geocoding, reports and civic issues.
 *
 * Categories, media and geocoding are built from the orval-generated
 * schemas (@civicpulse/api-client), with adapters noted where the app
 * needs something the spec doesn't say.
 *
 * Reports and issues are still hand-written (from "issues" down), on
 * purpose. Their generated counterparts require keys that the app, its
 * MSW mocks and test fixtures treat as optional, carry new required fields
 * nothing reads yet, and type match `signals` as a free-form object while
 * the review screens depend on its structure. Replacing them means
 * migrating the fixtures and mocks first; until then they keep the old
 * schemas, use the generated enums, and their requests go through the
 * generated client like everything else.
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
expectType<
  Same<CategoryFieldType, z.infer<typeof GenCategoryField.shape.type>>
>(true);

export const categoryFieldOptionSchema = FieldOption;
export type CategoryFieldOption = z.infer<typeof categoryFieldOptionSchema>;

export const categoryFieldSchema = GenCategoryField;
export type CategoryField = z.infer<typeof categoryFieldSchema>;

// Adapters: the spec always sends these keys and never `null` for
// `description_i18n`, `icon` or `dedup`; the app has always tolerated them
// missing or null, so it still does. `ai_prompts` and `severity_rules`
// (Phase 2), and `closure` (Phase 3), are required in the spec but optional
// until a screen edits them.
export const categorySchema = CategoryOut.extend({
  parent_id: CategoryOut.shape.parent_id.optional(),
  description_i18n: i18nTextSchema.nullish(),
  icon: CategoryOut.shape.icon.nullish(),
  fields: CategoryOut.shape.fields.default([]),
  default_department_id: CategoryOut.shape.default_department_id.optional(),
  dedup: CategoryOut.shape.dedup.nullish(),
  ai_prompts: CategoryOut.shape.ai_prompts.optional(),
  severity_rules: CategoryOut.shape.severity_rules.optional(),
  closure: CategoryOut.shape.closure.optional(),
});
export type Category = z.infer<typeof categorySchema>;

/** The category as embedded in reports and issues. */
// Adapter: `icon` may be missing or null, as above.
export const categorySummarySchema = CategoryRef.extend({
  icon: CategoryRef.shape.icon.nullish(),
});
export type CategorySummary = z.infer<typeof categorySummarySchema>;

// --------------------------------------------------------------------- media

/** What the upload pipeline accepts; the spec types it as a free string. */
export const ALLOWED_UPLOAD_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
] as const;
export type UploadContentType = (typeof ALLOWED_UPLOAD_TYPES)[number];

// Adapter: `headers` defaults to `{}`.
export const uploadTicketSchema = UploadCreated.extend({
  headers: UploadCreated.shape.headers.default({}),
});
export type UploadTicket = z.infer<typeof uploadTicketSchema>;

/**
 * Includes `pending` (the spec's MediaStatus): media embedded in a report
 * can still be waiting for processing.
 */
export const MEDIA_STATUSES = MediaStatus.options;
export const mediaStatusSchema = MediaStatus;

/** Returned by `POST /media/uploads/{id}/complete`. */
// Adapters: the nullable fields may also be missing, and `variants` (and
// either variant) may be missing or null.
export const mediaAssetSchema = MediaAssetOut.extend({
  width: MediaAssetOut.shape.width.optional(),
  height: MediaAssetOut.shape.height.optional(),
  variants: MediaVariants.partial().nullish(),
  captured_at: MediaAssetOut.shape.captured_at.optional(),
});
export type MediaAsset = z.infer<typeof mediaAssetSchema>;

/** Media as embedded in report and issue responses. */
// Adapter: every nullable field may also be missing.
export const mediaSchema = MediaOut.partial({
  width: true,
  height: true,
  thumb_url: true,
  display_url: true,
  original_url: true,
  captured_at: true,
});
export type Media = z.infer<typeof mediaSchema>;

// ----------------------------------------------------------------------- geo

/** A ward as embedded in reports and issues (the geocoder adds `code`). */
export const wardRefSchema = z.object({
  id: z.string(),
  name: z.string(),
  code: z.string().nullish(),
});
export type WardRef = z.infer<typeof wardRefSchema>;

// Adapter: `ward` and `zone` may also be missing, and a ward's `code`
// may be missing or null.
export const reverseGeocodeSchema = ReverseGeocodeOut.extend({
  ward: wardRefSchema.nullish(),
  zone: ReverseGeocodeOut.shape.zone.optional(),
});
export type ReverseGeocode = z.infer<typeof reverseGeocodeSchema>;

export const LOCATION_SOURCES = GenLocationSource.options;
export type LocationSource = z.infer<typeof GenLocationSource>;

// Adapter: `accuracy_m` may also be missing.
export const reportLocationSchema = LocationOut.extend({
  accuracy_m: LocationOut.shape.accuracy_m.optional(),
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
expectType<
  Same<(typeof ISSUE_STATUSES)[number], z.infer<typeof GenIssueStatus>>
>(true);
export const issueStatusSchema = GenIssueStatus;
export type IssueStatus = z.infer<typeof issueStatusSchema>;

export const publicTimelineEventSchema = z.object({
  at: z.string(),
  type: z.string(),
  from_status: issueStatusSchema.nullish(),
  to_status: issueStatusSchema.nullish(),
  public_note: z.string().nullish(),
});
export type PublicTimelineEvent = z.infer<typeof publicTimelineEventSchema>;

export const VERIFICATION_OUTCOMES = ["resolved", "unresolved"] as const;
export const verificationOutcomeSchema = z.enum(VERIFICATION_OUTCOMES);
export type VerificationOutcome = z.infer<typeof verificationOutcomeSchema>;

/** The closure round a reporter is asked to confirm (Phase 3 §6). */
export const citizenClosureSchema = z.object({
  state: z.enum(["pending", "approved"]),
  requested_at: z.string(),
  reason_code: z.string().nullish(),
  after_photos: z.array(mediaSchema).default([]),
});
export type CitizenClosure = z.infer<typeof citizenClosureSchema>;

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
      /** Community: citizens who said "I face this too". */
      support_count: z.number().default(0),
      /** Set while the issue is pending_verification, resolved or closed. */
      closure: citizenClosureSchema.nullish(),
      /** The caller's answer for the current closure round. */
      my_verification: verificationOutcomeSchema.nullish(),
      can_verify: z.boolean().default(false),
      can_reopen: z.boolean().default(false),
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
  /** The issue matching (or a reviewer) placed it on; null until then. */
  issue: z
    .object({
      id: z.string(),
      reference: z.string(),
      status: issueStatusSchema,
    })
    .nullish(),
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
  /** SLA resolution deadline; null when no target applies. */
  due_at: z.string().nullish(),
  overdue: z.boolean().default(false),
  sla_state: slaStateSchema.default("none"),
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
  visibility: Visibility,
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
  breached_at: z.string().nullish(),
  /** 0: none; 1: supervisors told; 2: municipal admins told. */
  escalation_level: z.number().default(0),
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
