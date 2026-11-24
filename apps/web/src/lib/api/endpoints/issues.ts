import { apiRequest } from "../client";
import { type Paginated, paginated } from "../schemas";
import type { PriorityBand, SeverityLevel } from "../schemas-ai";
import {
  type IssueDetail,
  type IssueFeatureCollection,
  type IssueListItem,
  type IssueStatus,
  issueDetailSchema,
  issueFeatureCollectionSchema,
  issueListItemSchema,
  type JurisdictionWithGeometry,
  jurisdictionWithGeometrySchema,
} from "../schemas-phase1";
import { type SplitResult, splitResultSchema } from "../schemas-phase2";

/** `-priority` is the staff default from Phase 2. */
export const ISSUE_SORTS = [
  "-priority",
  "-created_at",
  "created_at",
  "-updated_at",
  "-report_count",
] as const;
export type IssueSort = (typeof ISSUE_SORTS)[number];

/** Filters shared by the list and the map. All optional, ANDed together. */
export type IssueFilterParams = {
  status?: readonly IssueStatus[];
  category_id?: readonly string[];
  ward_id?: readonly string[];
  /** Calendar dates (YYYY-MM-DD), inclusive, in Asia/Kolkata. */
  from?: string;
  to?: string;
  q?: string;
  severity?: readonly SeverityLevel[];
  priority_band?: readonly PriorityBand[];
};

export type IssueListParams = IssueFilterParams & {
  sort?: IssueSort;
  limit?: number;
  offset?: number;
};

export function listIssues(
  params: IssueListParams,
  signal?: AbortSignal,
): Promise<Paginated<IssueListItem>> {
  return apiRequest({
    path: "/issues",
    query: params,
    schema: paginated(issueListItemSchema),
    signal,
  });
}

/** `bbox` is `[minLng, minLat, maxLng, maxLat]`. */
export function getIssuesGeoJson(
  params: IssueFilterParams & { bbox: readonly number[] },
  signal?: AbortSignal,
): Promise<IssueFeatureCollection> {
  return apiRequest({
    path: "/issues/geojson",
    query: { ...params, bbox: params.bbox.join(",") },
    schema: issueFeatureCollectionSchema,
    signal,
  });
}

export function getIssue(
  id: string,
  signal?: AbortSignal,
): Promise<IssueDetail> {
  return apiRequest({
    path: `/issues/${encodeURIComponent(id)}`,
    schema: issueDetailSchema,
    signal,
  });
}

export type ChangeStatusBody = {
  to_status: IssueStatus;
  reason?: string;
  public_note?: string;
  /** The version the user was looking at; a mismatch is a 409. */
  version: number;
};

export function changeIssueStatus(
  id: string,
  body: ChangeStatusBody,
): Promise<IssueDetail> {
  return apiRequest({
    method: "PATCH",
    path: `/issues/${encodeURIComponent(id)}/status`,
    body,
    schema: issueDetailSchema,
  });
}

/*
 * Phase 2 mutations. Each carries the version the user was looking at,
 * like the status change, and a 409 version_conflict means someone else
 * got there first: the dialogs explain and offer to reload rather than
 * retrying with the newer version.
 */

export function changeIssueCategory(
  id: string,
  body: { category_id: string; reason: string; version: number },
): Promise<IssueDetail> {
  return apiRequest({
    method: "PATCH",
    path: `/issues/${encodeURIComponent(id)}/category`,
    body,
    schema: issueDetailSchema,
  });
}

/** `severity: null` clears an override and goes back to the rules. */
export function setIssueSeverity(
  id: string,
  body: { severity: SeverityLevel | null; reason: string; version: number },
): Promise<IssueDetail> {
  return apiRequest({
    method: "PATCH",
    path: `/issues/${encodeURIComponent(id)}/severity`,
    body,
    schema: issueDetailSchema,
  });
}

/** `band: null` clears an override and goes back to the computed band. */
export function setIssuePriority(
  id: string,
  body: { band: PriorityBand | null; reason: string; version: number },
): Promise<IssueDetail> {
  return apiRequest({
    method: "PATCH",
    path: `/issues/${encodeURIComponent(id)}/priority`,
    body,
    schema: issueDetailSchema,
  });
}

/** `id` survives; the sources are merged into it. */
export function mergeIssues(
  id: string,
  body: { source_issue_ids: string[]; reason: string; version: number },
): Promise<IssueDetail> {
  return apiRequest({
    method: "POST",
    path: `/issues/${encodeURIComponent(id)}/merge`,
    body,
    schema: issueDetailSchema,
  });
}

export type SplitTarget = { new_issue: true } | { issue_id: string };

export function splitIssue(
  id: string,
  body: {
    report_ids: string[];
    target: SplitTarget;
    reason: string;
    version: number;
  },
): Promise<SplitResult> {
  return apiRequest({
    method: "POST",
    path: `/issues/${encodeURIComponent(id)}/split`,
    body,
    schema: splitResultSchema,
  });
}

export function addRelatedIssue(
  id: string,
  body: { issue_id: string; note?: string },
): Promise<void> {
  return apiRequest({
    method: "POST",
    path: `/issues/${encodeURIComponent(id)}/related`,
    body,
  });
}

export function removeRelatedIssue(id: string, otherId: string): Promise<void> {
  return apiRequest({
    method: "DELETE",
    path: `/issues/${encodeURIComponent(id)}/related/${encodeURIComponent(otherId)}`,
  });
}

/** Ward outlines for the map overlay. */
export function listWardBoundaries(
  signal?: AbortSignal,
): Promise<Paginated<JurisdictionWithGeometry>> {
  return apiRequest({
    path: "/admin/jurisdictions",
    query: { kind: "ward", include_geometry: true, limit: 100 },
    schema: paginated(jurisdictionWithGeometrySchema),
    signal,
  });
}
