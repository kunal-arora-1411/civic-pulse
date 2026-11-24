import { apiRequest } from "../client";
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
  return apiRequest({
    method: "POST",
    path: "/ai/classifications",
    body: { media_ids: mediaIds },
    schema: classificationSchema,
    signal,
  });
}

export function getClassification(
  id: string,
  signal?: AbortSignal,
): Promise<Classification> {
  return apiRequest({
    path: `/ai/classifications/${encodeURIComponent(id)}`,
    schema: classificationSchema,
    signal,
  });
}

export function getMatchingConfig(
  signal?: AbortSignal,
): Promise<MatchingConfig> {
  return apiRequest({
    path: "/admin/matching-config",
    schema: matchingConfigSchema,
    signal,
  });
}

export function updateMatchingConfig(
  body: MatchingConfig,
): Promise<MatchingConfig> {
  return apiRequest({
    method: "PUT",
    path: "/admin/matching-config",
    body,
    schema: matchingConfigSchema,
  });
}

export function getPriorityConfig(
  signal?: AbortSignal,
): Promise<PriorityConfig> {
  return apiRequest({
    path: "/admin/priority-config",
    schema: priorityConfigSchema,
    signal,
  });
}

export function updatePriorityConfig(
  body: PriorityConfig,
): Promise<PriorityConfig> {
  return apiRequest({
    method: "PUT",
    path: "/admin/priority-config",
    body,
    schema: priorityConfigSchema,
  });
}

export function listModels(signal?: AbortSignal): Promise<ModelRegistry> {
  return apiRequest({
    path: "/admin/ai/models",
    schema: modelRegistrySchema,
    signal,
  });
}

/** `from`/`to` are calendar dates (YYYY-MM-DD), whole days in IST. */
export function getAiQuality(
  params: { from: string; to: string },
  signal?: AbortSignal,
): Promise<AiQuality> {
  return apiRequest({
    path: "/admin/ai/quality",
    query: params,
    schema: aiQualitySchema,
    signal,
  });
}
