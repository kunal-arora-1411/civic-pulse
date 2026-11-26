import {
  adminAnnouncementsCreate,
  adminAnnouncementsList,
  adminAnnouncementsUpdate,
  adminAnnouncementsWithdraw,
  analyticsViewsCreate,
  analyticsViewsDelete,
  analyticsViewsList,
  analyticsViewsUpdate,
} from "@civicpulse/api-client";
import { apiRequest } from "../client";
import { TENANT } from "../config";
import { call, callVoid } from "../generated-client";
import { type Paginated, paginated } from "../schemas";
import {
  type AnalyticsView,
  type Announcement,
  type AnnouncementKind,
  type AnnouncementState,
  analyticsViewSchema,
  announcementSchema,
  type PublicAnnouncement,
  publicAnnouncementSchema,
  type SavedFilters,
} from "../schemas-extras";
import type { I18nText } from "../schemas-phase1";

// ------------------------------------------------ saved analytics views

export function listAnalyticsViews(
  signal?: AbortSignal,
): Promise<AnalyticsView[]> {
  return call(analyticsViewSchema.array(), (o) => analyticsViewsList(o), {
    signal,
  });
}

export type AnalyticsViewInput = {
  name: string;
  filters: SavedFilters;
  is_default?: boolean;
};

export function createAnalyticsView(
  body: AnalyticsViewInput,
): Promise<AnalyticsView> {
  return call(analyticsViewSchema, (o) => analyticsViewsCreate(body, o));
}

export function updateAnalyticsView(
  id: string,
  body: Partial<AnalyticsViewInput>,
): Promise<AnalyticsView> {
  return call(analyticsViewSchema, (o) => analyticsViewsUpdate(id, body, o));
}

export function deleteAnalyticsView(id: string): Promise<void> {
  return callVoid((o) => analyticsViewsDelete(id, o));
}

// ------------------------------------------------ service announcements

export type AnnouncementInput = {
  kind: AnnouncementKind;
  title_i18n: I18nText;
  body_i18n: I18nText;
  ward_id: string | null;
  category_id: string | null;
  starts_at: string;
  ends_at: string;
};

export function listAnnouncements(
  params: {
    state?: AnnouncementState;
    ward_id?: string;
    limit?: number;
    offset?: number;
  } = {},
  signal?: AbortSignal,
): Promise<Paginated<Announcement>> {
  return call(
    paginated(announcementSchema),
    (o) => adminAnnouncementsList(params, o),
    { signal },
  );
}

export function createAnnouncement(
  body: AnnouncementInput,
): Promise<Announcement> {
  return call(announcementSchema, (o) => adminAnnouncementsCreate(body, o));
}

export function updateAnnouncement(
  id: string,
  body: Partial<AnnouncementInput>,
): Promise<Announcement> {
  return call(announcementSchema, (o) => adminAnnouncementsUpdate(id, body, o));
}

export function withdrawAnnouncement(id: string): Promise<Announcement> {
  return call(announcementSchema, (o) => adminAnnouncementsWithdraw(id, o));
}

/** Public, no login: the notices showing now (see community.ts on caching). */
export function listPublicAnnouncements(
  params: { ward_id?: string; category_id?: string } = {},
  signal?: AbortSignal,
): Promise<PublicAnnouncement[]> {
  return apiRequest({
    path: `/public/${encodeURIComponent(TENANT)}/announcements`,
    query: params,
    schema: publicAnnouncementSchema.array(),
    auth: false,
    tenant: false,
    signal,
  });
}
