import {
  type Category,
  type CategorySuggestion,
  type Classification,
  getClassification,
  requestClassification,
} from "@/lib/api";
import type { ReportDraft } from "./draft";

/*
 * The AI category suggestion in the report flow (FR-020 to FR-022).
 *
 * The suggestion only ever helps: it pre-selects a category the citizen
 * can change, and nothing in the flow waits for it. If it's slow, fails,
 * isn't sure, or thinks the photo isn't a civic problem, the citizen
 * picks by hand exactly as before (PRD §8.6).
 */

export type SuggestionTiming = {
  /** Wait for the photo set to settle before asking. */
  debounceMs: number;
  /** How often to ask again while the API says `pending`. */
  pollMs: number;
  /** Stop asking after this long; the citizen just picks by hand. */
  timeoutMs: number;
};

export const SUGGESTION_TIMING: SuggestionTiming = {
  debounceMs: 800,
  pollMs: 1500,
  timeoutMs: 15_000,
};

/** A finished classification, as kept in the draft across reloads. */
export type DraftSuggestion = {
  /** The photo set it was made for (see `suggestionKey`). */
  key: string;
  id: string;
  suggestions: CategorySuggestion[];
  notCivic: boolean;
  needsManual: boolean;
};

/** Identifies a set of uploaded photos regardless of order. */
export function suggestionKey(mediaIds: readonly string[]): string {
  return [...mediaIds].sort().join(",");
}

export type SuggestionOutcome =
  | { status: "done"; result: Classification }
  | { status: "failed"; reason: "unavailable" | "timeout" | "error" };

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(signal.reason);
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(signal.reason);
      },
      { once: true },
    );
  });
}

/**
 * Ask for a classification and follow it to an outcome. The API waits up
 * to 4 s itself and answers 202 `pending` when it needs longer; then we
 * poll until `done` or `failed`, or give up at the timeout. Errors of any
 * kind count as "no suggestion", never as something to show the citizen.
 */
export async function runClassification(
  mediaIds: readonly string[],
  signal: AbortSignal,
  timing: Pick<SuggestionTiming, "pollMs" | "timeoutMs"> = SUGGESTION_TIMING,
  now: () => number = Date.now,
): Promise<SuggestionOutcome> {
  const started = now();
  try {
    let result = await requestClassification(mediaIds, signal);
    while (result.status === "pending") {
      if (now() - started + timing.pollMs > timing.timeoutMs) {
        return { status: "failed", reason: "timeout" };
      }
      await sleep(timing.pollMs, signal);
      result = await getClassification(result.id, signal);
    }
    return result.status === "done"
      ? { status: "done", result }
      : { status: "failed", reason: "unavailable" };
  } catch {
    return { status: "failed", reason: "error" };
  }
}

export function toDraftSuggestion(
  key: string,
  result: Classification,
): DraftSuggestion {
  return {
    key,
    id: result.id,
    suggestions: result.suggestions,
    notCivic: result.not_civic,
    needsManual: result.needs_manual,
  };
}

/**
 * The suggestion to pre-select, if any: the top one, when the model is
 * confident enough, thinks it's a civic problem, and names a category the
 * citizen can actually choose.
 */
export function topSuggestion(
  suggestion: DraftSuggestion | null | undefined,
  categories: readonly Pick<Category, "id">[],
): CategorySuggestion | null {
  if (!suggestion || suggestion.notCivic || suggestion.needsManual) return null;
  const top = suggestion.suggestions[0];
  if (!top || !categories.some((c) => c.id === top.category_id)) return null;
  return top;
}

/** "Looks like" for a confident suggestion, "might be" otherwise. */
export type ConfidenceWording = "looksLike" | "mightBe";

export function confidenceWording(confidence: number): ConfidenceWording {
  return confidence >= 0.7 ? "looksLike" : "mightBe";
}

function keepSharedDetails(
  details: ReportDraft["details"],
  category: Pick<Category, "fields"> | undefined,
): ReportDraft["details"] {
  if (!category) return {};
  return Object.fromEntries(
    Object.entries(details).filter(([key]) =>
      category.fields.some((field) => field.key === key),
    ),
  );
}

/**
 * Apply a settled classification to the draft on the category step.
 *
 * - A category the citizen chose themselves is never touched.
 * - A usable suggestion is pre-selected and remembered as shown, so its
 *   id goes with the report and the server can record whether it was
 *   accepted or corrected.
 * - If the photos changed and the new result has no usable suggestion,
 *   an earlier pre-selection is withdrawn rather than left standing on
 *   the strength of photos that are gone.
 *
 * Pass `null` for a classification that failed or timed out.
 */
export function applySuggestion(
  draft: ReportDraft,
  suggestion: DraftSuggestion | null,
  categories: readonly Category[],
): ReportDraft {
  if (draft.categorySource === "citizen") return draft;
  const top = topSuggestion(suggestion, categories);
  if (top && suggestion) {
    if (
      draft.categoryId === top.category_id &&
      draft.classificationId === suggestion.id
    ) {
      return draft;
    }
    return {
      ...draft,
      categoryId: top.category_id,
      categorySource: "ai",
      classificationId: suggestion.id,
      details: keepSharedDetails(
        draft.details,
        categories.find((c) => c.id === top.category_id),
      ),
    };
  }
  if (draft.categorySource === "ai") {
    return {
      ...draft,
      categoryId: null,
      categorySource: null,
      classificationId: null,
    };
  }
  return draft;
}

/**
 * The suggested categories first, best first, then the rest in their
 * usual order. Only reorders once a suggestion has actually been shown,
 * so tiles never jump under the citizen's finger after they've chosen.
 */
export function orderCategories<T extends Pick<Category, "id">>(
  categories: readonly T[],
  suggestion: DraftSuggestion | null | undefined,
  shown: boolean,
): { suggested: T[]; others: T[] } {
  if (!shown || !suggestion) return { suggested: [], others: [...categories] };
  const suggested = suggestion.suggestions.flatMap((item) => {
    const category = categories.find((c) => c.id === item.category_id);
    return category ? [category] : [];
  });
  const others = categories.filter((c) => !suggested.includes(c));
  return { suggested, others };
}
