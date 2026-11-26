import {
  Decision,
  Feedback,
  MatchingStatus as GenMatchingStatus,
  PriorityBand as GenPriorityBand,
  SeverityLevel as GenSeverityLevel,
  PriorityFactorOut,
  PriorityOut,
  SeverityOut,
} from "@civicpulse/api-client";
import { z } from "zod";
import { expectType, type Same } from "./type-checks";

/*
 * Building blocks of the Phase 2 contract (docs/api/phase-2-contract.md)
 * that the Phase 1 report and issue shapes embed: severity, priority and
 * the duplicate-matching signals. They import nothing from the other
 * schema files, so schemas-phase1.ts can use them without a cycle.
 *
 * Enums, severity and priority come from the orval-generated schemas
 * (@civicpulse/api-client). The ordered constants stay literal tuples
 * because the UI lists them in that order (the spec's enums aren't always
 * in display order); a type check ties each one to its generated enum.
 *
 * Match signals stay hand-written: the spec types `signals` as a
 * free-form object, but the review screens rely on its fields.
 */

/** Lowest to highest. Raises are capped at `critical`. */
export const SEVERITY_LEVELS = ["low", "medium", "high", "critical"] as const;
expectType<Same<(typeof SEVERITY_LEVELS)[number], GenSeverityLevel>>(true);
export const severityLevelSchema = GenSeverityLevel;
export type SeverityLevel = z.infer<typeof severityLevelSchema>;

/** Highest first, the order staff scan them in. */
export const PRIORITY_BANDS = ["critical", "high", "medium", "low"] as const;
expectType<Same<(typeof PRIORITY_BANDS)[number], GenPriorityBand>>(true);
export const priorityBandSchema = GenPriorityBand;
export type PriorityBand = z.infer<typeof priorityBandSchema>;

// Adapter: `reason` may also be missing.
export const severitySchema = SeverityOut.extend({
  /** How the rules got there, or why staff overrode it. */
  reason: SeverityOut.shape.reason.optional(),
});
export type Severity = z.infer<typeof severitySchema>;

// Adapter: the spec leaves `value` untyped; the UI formats it, so it is
// narrowed to what the contract lists.
export const priorityFactorSchema = PriorityFactorOut.extend({
  /** A level, a count, a number of days or a yes/no, depending on the factor. */
  value: z.union([z.string(), z.number(), z.boolean()]).nullish(),
});
export type PriorityFactor = z.infer<typeof priorityFactorSchema>;

// Adapters: one schema for the list shape (PriorityOut) and the detail
// shape (PriorityDetailOut, which adds `factors`), and `override_reason`
// may also be missing.
export const prioritySchema = PriorityOut.extend({
  override_reason: PriorityOut.shape.override_reason.optional(),
  /** Issue detail only, sorted by points, highest first. */
  factors: z.array(priorityFactorSchema).nullish(),
});
export type Priority = z.infer<typeof prioritySchema>;

export const MATCHING_STATUSES = [
  "pending",
  "linked",
  "review",
  "new_issue",
] as const;
expectType<Same<(typeof MATCHING_STATUSES)[number], GenMatchingStatus>>(true);
export const matchingStatusSchema = GenMatchingStatus;
export type MatchingStatus = z.infer<typeof matchingStatusSchema>;

export const matchSignalsSchema = z.object({
  distance_m: z.number(),
  radius_m: z.number(),
  geo: z.number(),
  /** Null when there were no embeddings (no photos, or the AI was down). */
  visual: z.number().nullable(),
  same_photo: z.boolean().default(false),
  category: z.number(),
  time: z.number(),
  age_days: z.number(),
  weights: z.object({
    geo: z.number(),
    visual: z.number(),
    category: z.number(),
    time: z.number(),
  }),
  thresholds: z.object({
    auto: z.number(),
    review: z.number(),
    visual_min: z.number(),
  }),
  /** `ai_unavailable` when matching fell back to the non-visual signals. */
  reason: z.string().nullish(),
});
export type MatchSignals = z.infer<typeof matchSignalsSchema>;

export const MATCH_DECISIONS = [
  "auto_linked",
  "sent_to_review",
  "rejected_candidate",
  "chosen_by_reviewer",
  "not_chosen",
] as const;
expectType<Same<(typeof MATCH_DECISIONS)[number], Decision>>(true);
export const matchDecisionKindSchema = Decision;
export type MatchDecisionKind = z.infer<typeof matchDecisionKindSchema>;

export const matchFeedbackSchema = Feedback;
export type MatchFeedback = z.infer<typeof matchFeedbackSchema>;

/** `match` on a staff report view: the decision that placed the report. */
export const reportMatchSchema = z.object({
  match_decision_id: z.string(),
  decision: matchDecisionKindSchema,
  score: z.number(),
  signals: matchSignalsSchema,
});
export type ReportMatch = z.infer<typeof reportMatchSchema>;

/** One candidate considered for a report, as listed on the issue detail. */
export const matchDecisionSchema = z.object({
  id: z.string(),
  candidate_issue: z.object({ id: z.string(), reference: z.string() }),
  rank: z.number(),
  score: z.number(),
  signals: matchSignalsSchema,
  decision: matchDecisionKindSchema,
  decided_by: z
    .object({ id: z.string(), display_name: z.string().nullable() })
    .nullish(),
  decided_at: z.string().nullish(),
  feedback: matchFeedbackSchema.nullish(),
});
export type MatchDecision = z.infer<typeof matchDecisionSchema>;
