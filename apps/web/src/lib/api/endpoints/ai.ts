import {
  adminGetAiQuality,
  adminGetMatchingConfig,
  adminGetPriorityConfig,
  adminListAiModels,
  adminUpdateMatchingConfig,
  adminUpdatePriorityConfig,
  aiCreateClassification,
  aiGetClassification,
} from "@civicpulse/api-client";
import { call } from "../generated-client";
import {
  type AiQuality,
  aiQualitySchema,
  type Classification,
  classificationSchema,
  type MatchingConfig,
  type ModelRegistry,
  matchingConfigSchema,
  modelRegistrySchema,
  type PriorityConfig,
  priorityConfigSchema,
} from "../schemas-phase2";

/**
 * Ask for a category suggestion for photos the caller has uploaded. The
 * API waits up to 4 s: a finished result comes back as 200, a slower one
 * as 202 with `status: "pending"` to poll. Both have the same shape, so
 * the status code doesn't matter here. If the AI is down the answer is
 * 200 with `status: "failed"`, and the citizen just picks by hand.
 */
export function requestClassification(
  mediaIds: readonly string[],
  signal?: AbortSignal,
): Promise<Classification> {
  return call(
    classificationSchema,
    (o) => aiCreateClassification({ media_ids: [...mediaIds] }, o),
    { signal },
  );
}

export function getClassification(
  id: string,
  signal?: AbortSignal,
): Promise<Classification> {
  return call(classificationSchema, (o) => aiGetClassification(id, o), {
    signal,
  });
}

export function getMatchingConfig(
  signal?: AbortSignal,
): Promise<MatchingConfig> {
  return call(matchingConfigSchema, (o) => adminGetMatchingConfig(o), {
    signal,
  });
}

export function updateMatchingConfig(
  body: MatchingConfig,
): Promise<MatchingConfig> {
  return call(matchingConfigSchema, (o) => adminUpdateMatchingConfig(body, o));
}

export function getPriorityConfig(
  signal?: AbortSignal,
): Promise<PriorityConfig> {
  return call(priorityConfigSchema, (o) => adminGetPriorityConfig(o), {
    signal,
  });
}

export function updatePriorityConfig(
  body: PriorityConfig,
): Promise<PriorityConfig> {
  return call(priorityConfigSchema, (o) => adminUpdatePriorityConfig(body, o));
}

export function listModels(signal?: AbortSignal): Promise<ModelRegistry> {
  return call(modelRegistrySchema, (o) => adminListAiModels(o), { signal });
}

/** `from`/`to` are calendar dates (YYYY-MM-DD), whole days in IST. */
export function getAiQuality(
  params: { from: string; to: string },
  signal?: AbortSignal,
): Promise<AiQuality> {
  return call(aiQualitySchema, (o) => adminGetAiQuality(params, o), {
    signal,
  });
}
