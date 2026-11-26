import {
  adminCreateTeam,
  adminGetClosureConfig,
  adminListTeams,
  adminUpdateClosureConfig,
  adminUpdateTeam,
  type BulkAction,
  BulkResult,
  issuesAddNote,
  issuesApproveClosure,
  issuesAssign,
  issuesAssignmentHistory,
  issuesBulk,
  issuesEligibleTeams,
  issuesRejectClosure,
  issuesReopen,
  reportsWithdraw,
  type TeamCreate,
  type TeamUpdate,
  workloadGet,
} from "@civicpulse/api-client";
import type { z } from "zod";
import { call } from "../generated-client";
import {
  assignmentsSchema,
  type ClosureConfig,
  closureConfigSchema,
  type EligibleTeam,
  eligibleTeamsSchema,
  type Team,
  type TeamPage,
  teamPageSchema,
  teamSchema,
  type Workload,
  workloadSchema,
} from "../schemas-operations";
import {
  type Assignment,
  type IssueDetail,
  type IssueTimelineEvent,
  issueDetailSchema,
  issueTimelineEventSchema,
  type Report,
  reportSchema,
} from "../schemas-phase1";

/*
 * Phase 3 staff operations (docs/api/phase-3-contract.md §1, §2, §4–§8).
 * Issue mutations carry the issue version the user was looking at; a 409
 * version_conflict means someone else changed it first.
 */

// ---------------------------------------------------------------- teams

export type TeamFilters = {
  department_id?: string;
  is_active?: boolean;
  limit?: number;
  offset?: number;
};

export function listTeams(
  filters: TeamFilters = {},
  signal?: AbortSignal,
): Promise<TeamPage> {
  return call(teamPageSchema, (o) => adminListTeams(filters, o), { signal });
}

export type TeamCreateBody = TeamCreate;
export type TeamUpdateBody = TeamUpdate;

export function createTeam(body: TeamCreateBody): Promise<Team> {
  return call(teamSchema, (o) => adminCreateTeam(body, o));
}

/** Lists in the body replace the stored ones. */
export function updateTeam(id: string, body: TeamUpdateBody): Promise<Team> {
  return call(teamSchema, (o) => adminUpdateTeam(id, body, o));
}

export function getEligibleTeams(
  issueId: string,
  signal?: AbortSignal,
): Promise<EligibleTeam[]> {
  return call(eligibleTeamsSchema, (o) => issuesEligibleTeams(issueId, o), {
    signal,
  });
}

// ------------------------------------------------------------ assignment

export type AssignBody = {
  team_id: string;
  assignee_id: string | null;
  note?: string;
  /** Required when reassigning. Internal. */
  reason?: string;
  version: number;
};

export function assignIssue(
  issueId: string,
  body: AssignBody,
): Promise<IssueDetail> {
  return call(issueDetailSchema, (o) => issuesAssign(issueId, body, o));
}

export function getAssignmentHistory(
  issueId: string,
  signal?: AbortSignal,
): Promise<Assignment[]> {
  return call(assignmentsSchema, (o) => issuesAssignmentHistory(issueId, o), {
    signal,
  });
}

// ------------------------------------------------------------------ notes

export type NoteBody = { body: string; visibility: "internal" | "public" };

export function addIssueNote(
  issueId: string,
  body: NoteBody,
): Promise<IssueTimelineEvent> {
  return call(issueTimelineEventSchema, (o) => issuesAddNote(issueId, body, o));
}

// ---------------------------------------------------------------- closure

export function approveClosure(
  issueId: string,
  body: { version: number; public_note?: string },
): Promise<IssueDetail> {
  return call(issueDetailSchema, (o) => issuesApproveClosure(issueId, body, o));
}

export function rejectClosure(
  issueId: string,
  body: { version: number; reason: string },
): Promise<IssueDetail> {
  return call(issueDetailSchema, (o) => issuesRejectClosure(issueId, body, o));
}

/**
 * Staff reopen of a resolved or closed issue (issue:update). Staff get the
 * issue detail back; citizens reopen through the community card instead.
 */
export function staffReopenIssue(
  issueId: string,
  body: { reason: string },
): Promise<IssueDetail> {
  return call(issueDetailSchema, (o) => issuesReopen(issueId, body, o));
}

export function getClosureConfig(signal?: AbortSignal): Promise<ClosureConfig> {
  return call(closureConfigSchema, (o) => adminGetClosureConfig(o), {
    signal,
  });
}

export function updateClosureConfig(
  body: ClosureConfig,
): Promise<ClosureConfig> {
  return call(closureConfigSchema, (o) => adminUpdateClosureConfig(body, o));
}

// --------------------------------------------------------------- workload

export function getWorkload(signal?: AbortSignal): Promise<Workload> {
  return call(workloadSchema, (o) => workloadGet(o), { signal });
}

// ---------------------------------------------------------------- reports

/** The reporter withdraws their own report (§7). */
export function withdrawReport(reportId: string): Promise<Report> {
  return call(reportSchema, (o) => reportsWithdraw(reportId, o));
}

// ------------------------------------------------------------------- bulk

export type BulkBody = BulkAction;
export type BulkOutcome = z.infer<typeof BulkResult>;

/**
 * Change the status of, or assign, up to 50 issues (FR-078). Each item
 * carries the version the user saw; refusals come back per item.
 */
export function bulkIssueAction(body: BulkBody): Promise<BulkOutcome> {
  return call(BulkResult, (o) => issuesBulk(body, o));
}
