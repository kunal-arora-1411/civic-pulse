"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";
import {
  type IssueFilters,
  parseIssueFilters,
  serializeIssueFilters,
  updateFilters,
} from "@/lib/issues/filters";

/**
 * Filters read from and written to the URL.
 *
 * Writes go through history.pushState/replaceState, which Next 16
 * integrates with its router: useSearchParams() updates, but there's no
 * server round trip for what is purely client-side state. Discrete
 * changes push a history entry so Back undoes them; typing in the search
 * box replaces the entry so Back doesn't step through every keystroke.
 *
 * useSearchParams() suspends during prerendering, so callers sit inside
 * a <Suspense> boundary.
 */
export function useIssueFilters() {
  const searchParams = useSearchParams();
  const query = searchParams.toString();
  // biome-ignore lint/correctness/useExhaustiveDependencies: the query string identifies the params
  const filters = useMemo(() => parseIssueFilters(searchParams), [query]);

  const setFilters = useCallback(
    (changes: Partial<IssueFilters>, options: { replace?: boolean } = {}) => {
      const current = parseIssueFilters(
        new URLSearchParams(window.location.search),
      );
      const next = serializeIssueFilters(updateFilters(current, changes));
      const search = next.toString();
      const url = `${window.location.pathname}${search ? `?${search}` : ""}`;
      if (options.replace) window.history.replaceState(null, "", url);
      else window.history.pushState(null, "", url);
    },
    [],
  );

  return { filters, setFilters };
}
