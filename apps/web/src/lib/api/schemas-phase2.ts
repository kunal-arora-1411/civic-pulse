import {
  ClassificationOut,
  type ClassificationStatus as GenClassificationStatus,
  MatchingConfig as GenMatchingConfig,
  PriorityConfig as GenPriorityConfig,
  MatchingThresholds,
  MatchingWeights,
  ModelList,
  ModelOut,
  PriorityBands,
  PriorityWeights,
  QualityOut,
  RecurrenceConfig,
  ReviewStatus,
  SeverityPoints,
  Suggestion,
} from "@civicpulse/api-client";
import { z } from "zod";
import { matchSignalsSchema } from "./schemas-ai";
import {
  issueDetailSchema,
  issueListItemSchema,
  staffReportSchema,
} from "./schemas-phase1";
import { expectType, type Same } from "./type-checks";

/*
 * Response schemas for the Phase 2 contract (docs/api/phase-2-contract.md)
 * that build on the Phase 1 shapes: category suggestions, review tasks,
 * merge and split results, and the configuration and governance screens.
 * Severity, priority and match signals live in schemas-ai.ts.
 *
 * Classification, configuration and governance come from the
 * orval-generated schemas (@civicpulse/api-client). Review tasks and split
 * results embed the hand-written report and issue shapes (see
 * schemas-phase1.ts for why), so they stay hand-written too.
 */

// ------------------------------------------------------- category suggestion

export const CLASSIFICATION_STATUSES = ["pending", "done", "failed"] as const;
export type ClassificationStatus = (typeof CLASSIFICATION_STATUSES)[number];
expectType<Same<ClassificationStatus, z.infer<typeof GenClassificationStatus>>>(
  true,
);

export const categorySuggestionSchema = Suggestion;
export type CategorySuggestion = z.infer<typeof categorySuggestionSchema>;

/** `POST /ai/classifications` (200 or 202) and `GET /ai/classifications/{id}`. */
// Adapters: the lists and flags default when missing, `model_id` and
// `error` may be missing, and `created_at` (required in the spec) is
// optional because nothing reads it.
export const classificationSchema = ClassificationOut.extend({
  model_id: ClassificationOut.shape.model_id.optional(),
  /** Active tenant categories only, best first, at most 3. */
  suggestions: ClassificationOut.shape.suggestions.default([]),
  not_civic: ClassificationOut.shape.not_civic.default(false),
  needs_manual: ClassificationOut.shape.needs_manual.default(false),
  /** `ai_unavailable` when the AI couldn't run. */
  error: ClassificationOut.shape.error.optional(),
  created_at: ClassificationOut.shape.created_at.optional(),
});
export type Classification = z.infer<typeof classificationSchema>;

// -------------------------------------------------------------- review tasks

export const reviewCandidateSchema = z.object({
  match_decision_id: z.string(),
  score: z.number(),
  signals: matchSignalsSchema,
  issue: issueListItemSchema,
});
export type ReviewCandidate = z.infer<typeof reviewCandidateSchema>;

export const reviewTaskSchema = z.object({
  id: z.string(),
  created_at: z.string(),
  status: ReviewStatus.default("open"),
  report: staffReportSchema,
  /** Best candidate first. */
  candidates: z.array(reviewCandidateSchema).default([]),
});
export type ReviewTask = z.infer<typeof reviewTaskSchema>;

// ---------------------------------------------------------------------- split

export const splitResultSchema = z.object({
  source: issueDetailSchema,
  target: issueDetailSchema,
});
export type SplitResult = z.infer<typeof splitResultSchema>;

// ------------------------------------------------------------ configuration

// Adapter: the spec shares one schema between the request and the
// response, so every field has a default and the nested objects are
// optional. The app always gets (and sends back) the full config, so the
// nested objects are required here, and `visual_min` is always present
// (`null` means the measured floor for the active vision model applies).
export const matchingConfigSchema = GenMatchingConfig.extend({
  weights: MatchingWeights,
  thresholds: MatchingThresholds.extend({
    visual_min: MatchingThresholds.shape.visual_min.unwrap(),
  }),
});
export type MatchingConfig = z.infer<typeof matchingConfigSchema>;

// Adapter: as for matching, the nested objects are required here.
export const priorityConfigSchema = GenPriorityConfig.extend({
  weights: PriorityWeights,
  severity_points: SeverityPoints,
  recurrence: RecurrenceConfig,
  bands: PriorityBands,
});
export type PriorityConfig = z.infer<typeof priorityConfigSchema>;

// ------------------------------------------------------------- AI governance

export const MODEL_TASKS = [
  "embedding",
  "classification",
  "face_detection",
] as const;
export type ModelTask = (typeof MODEL_TASKS)[number];

// Adapter: the descriptive fields may also be missing, and `deployed_at`
// and `metrics` may be null.
export const modelRegistryEntrySchema = ModelOut.extend({
  source: ModelOut.shape.source.optional(),
  license: ModelOut.shape.license.optional(),
  deployed_at: ModelOut.shape.deployed_at.nullish(),
  intended_use: ModelOut.shape.intended_use.optional(),
  metrics: ModelOut.shape.metrics.nullish(),
});
export type ModelRegistryEntry = z.infer<typeof modelRegistryEntrySchema>;

export const modelRegistrySchema = ModelList.extend({
  /** Newest deployment first. */
  items: z.array(modelRegistryEntrySchema),
});
export type ModelRegistry = z.infer<typeof modelRegistrySchema>;

export const aiQualitySchema = QualityOut;
export type AiQuality = z.infer<typeof aiQualitySchema>;
