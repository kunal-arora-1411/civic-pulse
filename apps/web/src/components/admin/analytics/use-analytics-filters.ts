"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";
import {
  type AnalyticsFilters,
  parseFilters,
  serializeFilters,
} from "@/lib/analytics/filters";

/**
 * The dashboard's filters, read from and written to the URL (the same
 * approach as the work queue: history.pushState, which Next 16 integrates
 * with useSearchParams, so there's no server round trip). Callers sit
 * inside a <Suspense> boundary because useSearchParams() suspends while
 * prerendering.
 */
export function useAnalyticsFilters() {
  const searchParams = useSearchParams();
  const query = searchParams.toString();
  // biome-ignore lint/correctness/useExhaustiveDependencies: the query string identifies the params
  const filters = useMemo(() => parseFilters(searchParams), [query]);

  const setFilters = useCallback(
    (
      changes: Partial<AnalyticsFilters>,
      options: { replace?: boolean } = {},
    ) => {
      const current = parseFilters(new URLSearchParams(window.location.search));
      const search = serializeFilters({ ...current, ...changes }).toString();
      // Replace when opening on a default view, so Back leaves the page
      // instead of returning to the unfiltered URL.
      const update = options.replace
        ? window.history.replaceState
        : window.history.pushState;
      update.call(
        window.history,
        null,
        "",
        `${window.location.pathname}${search ? `?${search}` : ""}`,
      );
    },
    [],
  );

  return { filters, setFilters };
}
