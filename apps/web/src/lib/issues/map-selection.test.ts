import { describe, expect, it } from "vitest";
import {
  clearCluster,
  EMPTY_SELECTION,
  listScrollTarget,
  mapFocusTarget,
  reconcileSelection,
  roundBbox,
  selectCluster,
  selectFromList,
  selectFromMap,
  visibleListItems,
} from "./map-selection";

const items = [{ id: "a" }, { id: "b" }, { id: "c" }];

describe("map/list selection", () => {
  it("highlights the row and scrolls to it when a marker is picked", () => {
    const state = selectFromMap(EMPTY_SELECTION, "b");
    expect(state.selectedId).toBe("b");
    expect(listScrollTarget(state)).toBe("b");
    // The map made the selection, so it shouldn't pan to itself.
    expect(mapFocusTarget(state)).toBeNull();
  });

  it("highlights the marker and pans to it when a row is picked", () => {
    const state = selectFromList(EMPTY_SELECTION, "c");
    expect(state.selectedId).toBe("c");
    expect(mapFocusTarget(state)).toBe("c");
    expect(listScrollTarget(state)).toBeNull();
  });

  it("deselects when the same marker is clicked twice", () => {
    const once = selectFromMap(EMPTY_SELECTION, "a");
    expect(selectFromMap(once, "a").selectedId).toBeNull();
  });

  it("narrows the list to a clicked cluster", () => {
    const state = selectCluster(["a", "c", "a"]);
    expect(state.clusterIds).toEqual(["a", "c"]);
    expect(visibleListItems(items, state).map((i) => i.id)).toEqual(["a", "c"]);
    expect(visibleListItems(items, clearCluster(state))).toHaveLength(3);
  });

  it("keeps the cluster when picking one of its markers, drops it otherwise", () => {
    const cluster = selectCluster(["a", "c"]);
    expect(selectFromMap(cluster, "c").clusterIds).toEqual(["a", "c"]);
    expect(selectFromMap(cluster, "b").clusterIds).toBeNull();
    // Picking a row inside the narrowed list keeps the narrowing.
    expect(selectFromList(cluster, "a").clusterIds).toEqual(["a", "c"]);
  });

  it("drops a selection whose issue left the data", () => {
    const state = selectFromList(selectCluster(["a", "b"]), "b");
    const next = reconcileSelection(state, new Set(["a", "c"]));
    expect(next).toEqual({
      selectedId: null,
      source: null,
      clusterIds: ["a"],
    });
  });

  it("returns the same object when nothing changed, to avoid re-renders", () => {
    const state = selectFromMap(EMPTY_SELECTION, "a");
    expect(reconcileSelection(state, new Set(["a", "b"]))).toBe(state);
  });

  it("rounds the bbox outwards so small pans reuse the request", () => {
    expect(roundBbox([77.5912, 12.9461, 77.6038, 12.9583])).toEqual([
      77.59, 12.94, 77.61, 12.96,
    ]);
    expect(roundBbox([77.5915, 12.9465, 77.6031, 12.9581])).toEqual(
      roundBbox([77.5912, 12.9461, 77.6038, 12.9583]),
    );
  });
});
