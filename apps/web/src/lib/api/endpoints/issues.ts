import {
  adminListJurisdictions,
  issuesAddRelated,
  issuesChangeStatus,
  issuesGeojson,
  issuesGet,
  issuesList,
  issuesMerge,
  issuesRemoveRelated,
  issuesSetCategory,
  issuesSetPriority,
  issuesSetSeverity,
  issuesSplit,
} from "@civicpulse/api-client";
import { z } from "zod";
import { call, callVoid, queryParams } from "../generated-client";
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
  type MergedIssue,
  mergedIssueSchema,
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
  return call(
    paginated(issueListItemSchema),
    (o) => issuesList(queryParams(params), o),
    { signal },
  );
}

/** `bbox` is `[minLng, minLat, maxLng, maxLat]`. */
export function getIssuesGeoJson(
  params: IssueFilterParams & { bbox: readonly number[] },
  signal?: AbortSignal,
): Promise<IssueFeatureCollection> {
  const query = queryParams({ ...params, bbox: params.bbox.join(",") });
  return call(issueFeatureCollectionSchema, (o) => issuesGeojson(query, o), {
    signal,
  });
}

// A merged issue is recognised first: it may carry only enough to
// redirect. A full detail with merged_into null falls through to it.
const issueOrMergedSchema = z.union([mergedIssueSchema, issueDetailSchema]);

export function isMergedIssue(
  issue: IssueDetail | MergedIssue,
): issue is MergedIssue {
  return "merged_into" in issue && Boolean(issue.merged_into);
}

/**
 * The issue detail, or a pointer to the surviving issue when this one
 * was merged away (the API answers 200 with `merged_into`).
 */
export function getIssue(
  id: string,
  signal?: AbortSignal,
): Promise<IssueDetail | MergedIssue> {
  return call(issueOrMergedSchema, (o) => issuesGet(id, o), { signal });
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
  return call(issueDetailSchema, (o) => issuesChangeStatus(id, body, o));
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
  return call(issueDetailSchema, (o) => issuesSetCategory(id, body, o));
}

/** `severity: null` clears an override and goes back to the rules. */
export function setIssueSeverity(
  id: string,
  body: { severity: SeverityLevel | null; reason: string; version: number },
): Promise<IssueDetail> {
  return call(issueDetailSchema, (o) => issuesSetSeverity(id, body, o));
}

/** `band: null` clears an override and goes back to the computed band. */
export function setIssuePriority(
  id: string,
  body: { band: PriorityBand | null; reason: string; version: number },
): Promise<IssueDetail> {
  return call(issueDetailSchema, (o) => issuesSetPriority(id, body, o));
}

/** `id` survives; the sources are merged into it. */
export function mergeIssues(
  id: string,
  body: { source_issue_ids: string[]; reason: string; version: number },
): Promise<IssueDetail> {
  return call(issueDetailSchema, (o) => issuesMerge(id, body, o));
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
  return call(splitResultSchema, (o) => issuesSplit(id, body, o));
}

export function addRelatedIssue(
  id: string,
  body: { issue_id: string; note?: string },
): Promise<void> {
  return callVoid((o) => issuesAddRelated(id, body, o));
}

export function removeRelatedIssue(id: string, otherId: string): Promise<void> {
  return callVoid((o) => issuesRemoveRelated(id, otherId, o));
}

/** Ward outlines for the map overlay. */
export function listWardBoundaries(
  signal?: AbortSignal,
): Promise<Paginated<JurisdictionWithGeometry>> {
  return call(
    paginated(jurisdictionWithGeometrySchema),
    (o) =>
      adminListJurisdictions(
        { kind: "ward", include_geometry: true, limit: 100 },
        o,
      ),
    { signal },
  );
}
