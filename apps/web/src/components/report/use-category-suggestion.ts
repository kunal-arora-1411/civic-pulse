"use client";

import { useEffect, useRef, useState } from "react";
import {
  type DraftSuggestion,
  runClassification,
  SUGGESTION_TIMING,
  type SuggestionTiming,
  suggestionKey,
  toDraftSuggestion,
} from "@/lib/report/suggestion";

export type SuggestionState =
  /** No photos uploaded yet. */
  | { status: "idle" }
  /** Waiting for the photo set to settle, asking, or polling. */
  | { status: "loading" }
  | { status: "done"; suggestion: DraftSuggestion }
  /** Failed, unavailable or timed out: the citizen picks by hand. */
  | { status: "failed" };

type Settled = { key: string } & (
  | { status: "loading" }
  | { status: "done"; suggestion: DraftSuggestion }
  | { status: "failed" }
);

/**
 * Asks for a category suggestion as soon as the first photo has
 * uploaded, and again (after a pause) whenever the set of uploaded photos
 * changes. A finished result is handed to `onResult` to be kept in the
 * draft; when the draft already holds one for these photos, nothing is
 * requested.
 *
 * Like the uploads, a request isn't tied to the step being shown: the
 * citizen usually moves on to the location step while it runs. It is
 * cancelled only when the photos change or the flow unmounts. When the
 * route is hidden inside <Activity> the effect is torn down and runs
 * again on return, which simply asks again if nothing was stored.
 */
export function useCategorySuggestion({
  mediaIds,
  stored,
  onResult,
  timing = SUGGESTION_TIMING,
}: {
  mediaIds: readonly string[];
  stored: DraftSuggestion | null | undefined;
  onResult: (suggestion: DraftSuggestion) => void;
  timing?: SuggestionTiming;
}): SuggestionState {
  const key = suggestionKey(mediaIds);
  const storedMatches = Boolean(key) && stored?.key === key;
  const [settled, setSettled] = useState<Settled | null>(null);
  const idsRef = useRef(mediaIds);
  idsRef.current = mediaIds;
  const onResultRef = useRef(onResult);
  onResultRef.current = onResult;

  useEffect(() => {
    if (!key || storedMatches) return;
    const controller = new AbortController();
    const { signal } = controller;
    const timer = setTimeout(async () => {
      setSettled({ key, status: "loading" });
      const outcome = await runClassification(idsRef.current, signal, timing);
      if (signal.aborted) return;
      if (outcome.status === "done") {
        const suggestion = toDraftSuggestion(key, outcome.result);
        setSettled({ key, status: "done", suggestion });
        onResultRef.current(suggestion);
      } else {
        setSettled({ key, status: "failed" });
      }
    }, timing.debounceMs);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [key, storedMatches, timing]);

  if (!key) return { status: "idle" };
  if (storedMatches && stored) return { status: "done", suggestion: stored };
  if (settled?.key === key && settled.status !== "loading") {
    return settled.status === "done"
      ? { status: "done", suggestion: settled.suggestion }
      : { status: "failed" };
  }
  return { status: "loading" };
}
