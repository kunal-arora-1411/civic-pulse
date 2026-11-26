import {
  ClosureConfig as GenClosureConfig,
  DepartmentRef as GenDepartmentRef,
  EligibleTeam as GenEligibleTeam,
  FieldIssue as GenFieldIssue,
  FieldWorkOrder as GenFieldWorkOrder,
  MediaPhase as GenMediaPhase,
  ProgressUpdateOut as GenProgressUpdateOut,
  TeamLoad as GenTeamLoad,
  TeamMemberOut as GenTeamMemberOut,
  TeamOut as GenTeamOut,
  WorkOrderState as GenWorkOrderState,
} from "@civicpulse/api-client";
import { z } from "zod";
import {
  assignmentSchema,
  categorySummarySchema,
  mediaSchema,
} from "./schemas-phase1";

/*
 * Phase 3: operations and field (docs/api/phase-3-contract.md). Built from
 * the generated schemas; the only adapters are the app's lenient media and
 * category shapes, so photos embedded here parse like everywhere else.
 */

// ---------------------------------------------------------------- teams

export const teamMemberSchema = GenTeamMemberOut;
export type TeamMember = z.infer<typeof teamMemberSchema>;

export const departmentRefSchema = GenDepartmentRef;
export type DepartmentRef = z.infer<typeof departmentRefSchema>;

export const teamSchema = GenTeamOut;
export type Team = z.infer<typeof teamSchema>;

export const teamPageSchema = z.object({
  items: z.array(teamSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});
export type TeamPage = z.infer<typeof teamPageSchema>;

export const eligibleTeamSchema = GenEligibleTeam;
export type EligibleTeam = z.infer<typeof eligibleTeamSchema>;
export const eligibleTeamsSchema = z.array(eligibleTeamSchema);

// ------------------------------------------------------------ assignment

export const WORK_ORDER_STATES = GenWorkOrderState.options;
export const workOrderStateSchema = GenWorkOrderState;
export type WorkOrderState = z.infer<typeof workOrderStateSchema>;

/** States in which the work order still needs someone to act. */
export const OPEN_WORK_ORDER_STATES: readonly WorkOrderState[] = [
  "pending_acceptance",
  "accepted",
  "in_progress",
  "completion_requested",
];

export const assignmentsSchema = z.array(assignmentSchema);

// ---------------------------------------------------------------- closure

export const closureConfigSchema = GenClosureConfig;
export type ClosureConfig = z.infer<typeof closureConfigSchema>;

// ------------------------------------------------------------------ field

export const MEDIA_PHASES = GenMediaPhase.options;
export type MediaPhase = z.infer<typeof GenMediaPhase>;

export const evidenceSchema = mediaSchema.extend({ phase: GenMediaPhase });
export type Evidence = z.infer<typeof evidenceSchema>;

export const fieldIssueSchema = GenFieldIssue.extend({
  category: categorySummarySchema,
  photos: z.array(mediaSchema).default([]),
  descriptions: z.array(z.string()).default([]),
});
export type FieldIssue = z.infer<typeof fieldIssueSchema>;

export const workOrderSchema = GenFieldWorkOrder.extend({
  issue: fieldIssueSchema,
  evidence: z.array(evidenceSchema).default([]),
  updates: z.array(GenProgressUpdateOut).default([]),
});
export type WorkOrder = z.infer<typeof workOrderSchema>;

export const workOrderPageSchema = z.object({
  items: z.array(workOrderSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});
export type WorkOrderPage = z.infer<typeof workOrderPageSchema>;

// --------------------------------------------------------------- workload

export const teamLoadSchema = GenTeamLoad.extend({
  /** Null until SLA targets exist. */
  overdue: z.number().nullish(),
});
export type TeamLoad = z.infer<typeof teamLoadSchema>;
export const workloadSchema = z.object({ items: z.array(teamLoadSchema) });
export type Workload = z.infer<typeof workloadSchema>;
