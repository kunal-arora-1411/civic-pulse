/*
 * Map/list selection for the staff map (FR-050): picking a marker
 * highlights and scrolls to its row, picking a row highlights and pans to
 * its marker, and picking a cluster narrows the list to the issues in it.
 * Kept free of Leaflet and React so the rules are easy to test.
 */

export type SelectionSource = "map" | "list";

export type MapSelection = {
  selectedId: string | null;
  /** Where the selection came from, so the *other* side reacts. */
  source: SelectionSource | null;
  /** Issue ids of a clicked cluster; the list shows only these. */
  clusterIds: string[] | null;
};

export const EMPTY_SELECTION: MapSelection = {
  selectedId: null,
  source: null,
  clusterIds: null,
};

export function selectFromMap(state: MapSelection, id: string): MapSelection {
  // Clicking the selected marker again deselects it.
  if (state.selectedId === id && state.source === "map") {
    return { ...state, selectedId: null, source: null };
  }
  const inCluster = state.clusterIds?.includes(id) ?? false;
  return {
    selectedId: id,
    source: "map",
    clusterIds: inCluster ? state.clusterIds : null,
  };
}

export function selectFromList(state: MapSelection, id: string): MapSelection {
  return { ...state, selectedId: id, source: "list" };
}

export function selectCluster(ids: readonly string[]): MapSelection {
  return { selectedId: null, source: "map", clusterIds: [...new Set(ids)] };
}

export function clearCluster(state: MapSelection): MapSelection {
  return { ...state, clusterIds: null };
}

/**
 * After new data arrives (filters changed, map moved), drop a selection
 * whose issue is gone and trim the cluster to what's still there.
 */
export function reconcileSelection(
  state: MapSelection,
  availableIds: ReadonlySet<string>,
): MapSelection {
  const selectedId =
    state.selectedId && availableIds.has(state.selectedId)
      ? state.selectedId
      : null;
  const clusterIds = state.clusterIds
    ? state.clusterIds.filter((id) => availableIds.has(id))
    : null;
  const next: MapSelection = {
    selectedId,
    source: selectedId ? state.source : null,
    clusterIds: clusterIds && clusterIds.length > 0 ? clusterIds : null,
  };
  const unchanged =
    next.selectedId === state.selectedId &&
    next.source === state.source &&
    (next.clusterIds?.join() ?? null) === (state.clusterIds?.join() ?? null);
  return unchanged ? state : next;
}

/** The rows to show: the clicked cluster, or everything in view. */
export function visibleListItems<T extends { id: string }>(
  items: readonly T[],
  state: MapSelection,
): T[] {
  if (!state.clusterIds) return [...items];
  const wanted = new Set(state.clusterIds);
  return items.filter((item) => wanted.has(item.id));
}

/** The row to scroll into view: only when the map made the selection. */
export function listScrollTarget(state: MapSelection): string | null {
  return state.source === "map" ? state.selectedId : null;
}

/** The marker to pan to: only when the list made the selection. */
export function mapFocusTarget(state: MapSelection): string | null {
  return state.source === "list" ? state.selectedId : null;
}

export type Bbox = [number, number, number, number];

/**
 * A cache key for the visible area, rounded to about 1 km so tiny pans
 * reuse the previous request instead of refetching. The fetched box is
 * padded to match, so rounding never leaves markers missing at the edges.
 */
export function roundBbox(bbox: Bbox, step = 0.01): Bbox {
  const [minLng, minLat, maxLng, maxLat] = bbox;
  const down = (value: number) => Math.floor(value / step) * step;
  const up = (value: number) => Math.ceil(value / step) * step;
  const fix = (value: number) => Number(value.toFixed(6));
  return [
    fix(down(minLng)),
    fix(down(minLat)),
    fix(up(maxLng)),
    fix(up(maxLat)),
  ];
}
