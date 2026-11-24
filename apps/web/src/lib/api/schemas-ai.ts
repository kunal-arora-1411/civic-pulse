import { z } from "zod";

/*
 * Building blocks of the Phase 2 contract (docs/api/phase-2-contract.md)
 * that the Phase 1 report and issue shapes embed: severity, priority and
 * the duplicate-matching signals. They import nothing from the other
 * schema files, so schemas-phase1.ts can use them without a cycle.
 */

/** Lowest to highest. Raises are capped at `critical`. */
export const SEVERITY_LEVELS = ["low", "medium", "high", "critical"] as const;
export const severityLevelSchema = z.enum(SEVERITY_LEVELS);
export type SeverityLevel = z.infer<typeof severityLevelSchema>;

/** Highest first, the order staff scan them in. */
export const PRIORITY_BANDS = ["critical", "high", "medium", "low"] as const;
export const priorityBandSchema = z.enum(PRIORITY_BANDS);
export type PriorityBand = z.infer<typeof priorityBandSchema>;

export const severitySchema = z.object({
  level: severityLevelSchema,
  source: z.enum(["rule", "override"]),
  /** Why staff overrode it. Detail only, and only when overridden. */
  reason: z.string().nullish(),
});
export type Severity = z.infer<typeof severitySchema>;

export const priorityFactorSchema = z.object({
  factor: z.string(),
  /** A level, a count, a number of days or a yes/no, depending on the factor. */
  value: z.union([z.string(), z.number(), z.boolean()]).nullish(),
  normalized: z.number(),
  points: z.number(),
  explanation_key: z.string(),
});
export type PriorityFactor = z.infer<typeof priorityFactorSchema>;

export const prioritySchema = z.object({
  score: z.number(),
  /** The effective band: the override when there is one. */
  band: priorityBandSchema,
  computed_band: priorityBandSchema,
  overridden: z.boolean(),
  override_reason: z.string().nullish(),
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
export const matchingStatusSchema = z.enum(MATCHING_STATUSES);
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
export const matchDecisionKindSchema = z.enum(MATCH_DECISIONS);
export type MatchDecisionKind = z.infer<typeof matchDecisionKindSchema>;

export const matchFeedbackSchema = z.enum(["correct", "incorrect"]);
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
