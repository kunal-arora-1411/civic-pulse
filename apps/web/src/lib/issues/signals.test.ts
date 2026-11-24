import { describe, expect, it } from "vitest";
import { makeSignals } from "@/test/signals";
import { matchVerdict, signalRows } from "./signals";

describe("signalRows", () => {
  it("weights each signal and sums to the score", () => {
    const rows = signalRows(makeSignals());
    expect(rows.map((row) => [row.key, row.weight])).toEqual([
      ["geo", 0.4],
      ["visual", 0.4],
      ["category", 0.1],
      ["time", 0.1],
    ]);
    const total = rows.reduce((sum, row) => sum + row.points, 0);
    expect(total).toBeCloseTo(0.4 * 0.54 + 0.4 * 0.91 + 0.1 + 0.093);
  });

  it("re-normalises the other weights when there was no photo comparison", () => {
    const rows = signalRows(makeSignals({ visual: null }));
    const byKey = Object.fromEntries(rows.map((row) => [row.key, row]));
    expect(byKey.visual).toMatchObject({ value: null, weight: 0, points: 0 });
    expect(byKey.geo.weight).toBeCloseTo(0.4 / 0.6);
    expect(byKey.category.weight).toBeCloseTo(0.1 / 0.6);
    expect(rows.reduce((sum, row) => sum + row.weight, 0)).toBeCloseTo(1);
  });
});

describe("matchVerdict", () => {
  it("auto-links only when score, photos and distance all pass", () => {
    expect(matchVerdict(0.9, makeSignals())).toEqual({ kind: "auto" });
    expect(matchVerdict(0.9, makeSignals({ visual: 0.7 }))).toEqual({
      kind: "auto_blocked",
      why: "visual",
    });
    expect(matchVerdict(0.9, makeSignals({ distance_m: 45 }))).toEqual({
      kind: "auto_blocked",
      why: "distance",
    });
    expect(matchVerdict(0.9, makeSignals({ visual: null }))).toEqual({
      kind: "auto_blocked",
      why: "no_visual",
    });
  });

  it("places other scores against the review threshold", () => {
    expect(matchVerdict(0.6, makeSignals()).kind).toBe("review");
    expect(matchVerdict(0.59, makeSignals()).kind).toBe("low");
  });
});
