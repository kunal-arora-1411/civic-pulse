import { z } from "zod";
import { matchSignalsSchema } from "./schemas-ai";
import {
  issueDetailSchema,
  issueListItemSchema,
  staffReportSchema,
} from "./schemas-phase1";

/*
 * Response schemas for the Phase 2 contract (docs/api/phase-2-contract.md)
 * that build on the Phase 1 shapes: category suggestions, review tasks,
 * merge and split results, and the configuration and governance screens.
 * Severity, priority and match signals live in schemas-ai.ts.
 */

// ------------------------------------------------------- category suggestion

export const CLASSIFICATION_STATUSES = ["pending", "done", "failed"] as const;
export type ClassificationStatus = (typeof CLASSIFICATION_STATUSES)[number];

export const categorySuggestionSchema = z.object({
  category_id: z.string(),
  code: z.string(),
  /** 0–1. Never shown to citizens as a number. */
  confidence: z.number(),
});
export type CategorySuggestion = z.infer<typeof categorySuggestionSchema>;

/** `POST /ai/classifications` (200 or 202) and `GET /ai/classifications/{id}`. */
export const classificationSchema = z.object({
  id: z.string(),
  status: z.enum(CLASSIFICATION_STATUSES),
  model_id: z.string().nullish(),
  /** Active tenant categories only, best first, at most 3. */
  suggestions: z.array(categorySuggestionSchema).default([]),
  not_civic: z.boolean().default(false),
  needs_manual: z.boolean().default(false),
  /** `ai_unavailable` when the AI couldn't run. */
  error: z.string().nullish(),
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
  status: z.enum(["open", "resolved"]).default("open"),
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

const signalWeights = z.object({
  geo: z.number(),
  visual: z.number(),
  category: z.number(),
  time: z.number(),
});

export const matchingConfigSchema = z.object({
  auto_link_enabled: z.boolean(),
  weights: signalWeights,
  thresholds: z.object({
    auto: z.number(),
    review: z.number(),
    visual_min: z.number(),
  }),
  classification_threshold: z.number(),
  fallback_review_threshold: z.number(),
});
export type MatchingConfig = z.infer<typeof matchingConfigSchema>;

export const priorityConfigSchema = z.object({
  weights: z.object({
    severity: z.number(),
    reporters: z.number(),
    age: z.number(),
    recurrence: z.number(),
    near_places: z.number(),
  }),
  severity_points: z.object({
    low: z.number(),
    medium: z.number(),
    high: z.number(),
    critical: z.number(),
  }),
  reporters_saturation: z.number(),
  age_saturation_days: z.number(),
  recurrence: z.object({
    radius_m: z.number(),
    lookback_days: z.number(),
    saturation: z.number(),
  }),
  bands: z.object({
    critical: z.number(),
    high: z.number(),
    medium: z.number(),
  }),
});
export type PriorityConfig = z.infer<typeof priorityConfigSchema>;

// ------------------------------------------------------------- AI governance

export const MODEL_TASKS = [
  "embedding",
  "classification",
  "face_detection",
] as const;
export type ModelTask = (typeof MODEL_TASKS)[number];

export const modelRegistryEntrySchema = z.object({
  model_id: z.string(),
  task: z.string(),
  name: z.string(),
  version: z.string(),
  source: z.string().nullish(),
  license: z.string().nullish(),
  deployed_at: z.string().nullish(),
  intended_use: z.string().nullish(),
  metrics: z.record(z.string(), z.unknown()).nullish(),
  /** The model in use for its task: the one deployed most recently. */
  active: z.boolean(),
});
export type ModelRegistryEntry = z.infer<typeof modelRegistryEntrySchema>;

export const modelRegistrySchema = z.object({
  /** Newest deployment first. */
  items: z.array(modelRegistryEntrySchema),
});
export type ModelRegistry = z.infer<typeof modelRegistrySchema>;

export const aiQualitySchema = z.object({
  from: z.string(),
  to: z.string(),
  classifications: z.object({
    done: z.number(),
    failed: z.number(),
    /** Reports whose citizen kept the top suggestion, by category code. */
    accepted_by_category: z.record(z.string(), z.number()),
    /** Reports whose citizen chose another category, by the chosen code. */
    corrected_by_category: z.record(z.string(), z.number()),
  }),
  matching: z.object({
    auto_linked: z.number(),
    sent_to_review: z.number(),
    new_issue: z.number(),
  }),
  reviews: z.object({ linked: z.number(), new_issue: z.number() }),
  auto_link_feedback: z.object({
    correct: z.number(),
    incorrect: z.number(),
  }),
});
export type AiQuality = z.infer<typeof aiQualitySchema>;
