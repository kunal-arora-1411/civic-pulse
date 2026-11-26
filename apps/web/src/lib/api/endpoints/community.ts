import { apiRequest } from "../client";
import { TENANT } from "../config";
import type { Paginated } from "../schemas";
import {
  type PublicFeatureCollection,
  type PublicIssueDetail,
  type PublicIssueItem,
  type PublicSort,
  publicFeatureCollectionSchema,
  publicIssueDetailSchema,
  publicIssuePageSchema,
  type Scorecard,
  type SupportState,
  scorecardSchema,
  supportStateSchema,
} from "../schemas-community";
import {
  type IssueStatus,
  type Report,
  reportSchema,
  type VerificationOutcome,
} from "../schemas-phase1";

// ---------------------------------------------- support ("I face this too")

const supportPath = (issueId: string) =>
  `/issues/${encodeURIComponent(issueId)}/support`;

export function getSupport(
  issueId: string,
  signal?: AbortSignal,
): Promise<SupportState> {
  return apiRequest({
    path: supportPath(issueId),
    schema: supportStateSchema,
    signal,
  });
}

/** POST to support, DELETE to withdraw. Both are idempotent. */
export function setSupport(
  issueId: string,
  supported: boolean,
): Promise<SupportState> {
  return apiRequest({
    method: supported ? "POST" : "DELETE",
    path: supportPath(issueId),
    schema: supportStateSchema,
  });
}

// ------------------------------------------------ verification and reopen

/** The reporter says whether the issue is fixed; returns their report. */
export function verifyIssue(
  issueId: string,
  body: { outcome: VerificationOutcome; note?: string },
): Promise<Report> {
  return apiRequest({
    method: "POST",
    path: `/issues/${encodeURIComponent(issueId)}/verification`,
    body,
    schema: reportSchema,
  });
}

/** A reporter reopens a resolved or closed issue; returns their report. */
export function reopenIssue(
  issueId: string,
  body: { reason: string },
): Promise<Report> {
  return apiRequest({
    method: "POST",
    path: `/issues/${encodeURIComponent(issueId)}/reopen`,
    body,
    schema: reportSchema,
  });
}

// ---------------------------------------------- public tracking (no login)

export type PublicIssueFilters = {
  status?: IssueStatus[];
  category_id?: string;
  ward_id?: string;
};

/*
 * The tenant is in the path, so these send neither a token nor X-Tenant:
 * the same URL gives everyone the same response, which keeps it cacheable.
 */
const publicPath = (rest: string) =>
  `/public/${encodeURIComponent(TENANT)}${rest}`;

export function listPublicIssues(
  params: PublicIssueFilters & {
    sort?: PublicSort;
    limit?: number;
    offset?: number;
  } = {},
  signal?: AbortSignal,
): Promise<Paginated<PublicIssueItem>> {
  return apiRequest({
    path: publicPath("/issues"),
    query: params,
    schema: publicIssuePageSchema,
    auth: false,
    tenant: false,
    signal,
  });
}

export function getPublicIssuesGeojson(
  params: PublicIssueFilters = {},
  signal?: AbortSignal,
): Promise<PublicFeatureCollection> {
  return apiRequest({
    path: publicPath("/issues/geojson"),
    query: params,
    schema: publicFeatureCollectionSchema,
    auth: false,
    tenant: false,
    signal,
  });
}

export function getPublicIssue(
  id: string,
  signal?: AbortSignal,
): Promise<PublicIssueDetail> {
  return apiRequest({
    path: publicPath(`/issues/${encodeURIComponent(id)}`),
    schema: publicIssueDetailSchema,
    auth: false,
    tenant: false,
    signal,
  });
}

export function getScorecard(signal?: AbortSignal): Promise<Scorecard> {
  return apiRequest({
    path: publicPath("/scorecard"),
    schema: scorecardSchema,
    auth: false,
    tenant: false,
    signal,
  });
}
