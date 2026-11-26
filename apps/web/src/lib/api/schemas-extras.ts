import { z } from "zod";
import { i18nTextSchema, issueStatusSchema } from "./schemas-phase1";

/*
 * Saved analytics views and service announcements
 * (docs/api/saved-views-announcements.md).
 */

export const savedFiltersSchema = z.object({
  range: z.enum(["7d", "30d", "90d", "mtd", "custom"]).default("30d"),
  from: z.string().nullable().default(null),
  to: z.string().nullable().default(null),
  category_id: z.string().nullable().default(null),
  ward_id: z.string().nullable().default(null),
  status: z.array(issueStatusSchema).default([]),
  interval: z.enum(["day", "week"]).default("day"),
});
export type SavedFilters = z.infer<typeof savedFiltersSchema>;

export const analyticsViewSchema = z.object({
  id: z.string(),
  name: z.string(),
  filters: savedFiltersSchema,
  is_default: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type AnalyticsView = z.infer<typeof analyticsViewSchema>;

export const ANNOUNCEMENT_KINDS = [
  "planned_works",
  "outage",
  "advisory",
] as const;
export type AnnouncementKind = (typeof ANNOUNCEMENT_KINDS)[number];

export const ANNOUNCEMENT_STATES = [
  "active",
  "scheduled",
  "ended",
  "withdrawn",
] as const;
export type AnnouncementState = (typeof ANNOUNCEMENT_STATES)[number];

const wardRefSchema = z.object({
  id: z.string(),
  code: z.string(),
  name: z.string(),
});

const categoryRefSchema = z.object({
  id: z.string(),
  code: z.string(),
  name_i18n: i18nTextSchema,
  icon: z.string().nullable().optional(),
});

export const publicAnnouncementSchema = z.object({
  id: z.string(),
  kind: z.enum(ANNOUNCEMENT_KINDS),
  title_i18n: i18nTextSchema,
  body_i18n: i18nTextSchema,
  ward: wardRefSchema.nullable(),
  category: categoryRefSchema.nullable(),
  starts_at: z.string(),
  ends_at: z.string(),
});
export type PublicAnnouncement = z.infer<typeof publicAnnouncementSchema>;

export const announcementSchema = publicAnnouncementSchema.extend({
  state: z.enum(ANNOUNCEMENT_STATES),
  withdrawn_at: z.string().nullable(),
  created_by: z
    .object({ id: z.string(), display_name: z.string().nullable() })
    .nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Announcement = z.infer<typeof announcementSchema>;
