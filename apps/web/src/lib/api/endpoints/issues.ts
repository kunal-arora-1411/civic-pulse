import { apiRequest } from "../client";
import { type Paginated, paginated } from "../schemas";
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

export const ISSUE_SORTS = [
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
