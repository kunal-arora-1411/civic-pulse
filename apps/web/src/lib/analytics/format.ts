/*
 * How analytics figures read. Hours become days past two days, ratios are
 * percentages, and a change is a relative change for counts and durations
 * but percentage points for ratios (a 10% → 12% move is +2 pts, not +20%).
 */

export type Unit = "count" | "hours" | "ratio";

export type Delta = {
  /** Signed change: relative for counts and hours, points for ratios. */
  change: number;
  kind: "percent" | "points";
};

export function delta(
  unit: Unit,
  value: number | null,
  previous: number | null,
): Delta | null {
  if (value === null || previous === null) return null;
  if (unit === "ratio")
    return { change: (value - previous) * 100, kind: "points" };
  if (previous === 0) return null;
  return { change: (value - previous) / previous, kind: "percent" };
}

/** Lower is better for these; for the rest a change is neutral. */
const LOWER_IS_BETTER = new Set([
  "resolution_time",
  "acknowledgement_time",
  "reopen_rate",
]);

export function deltaTone(
  metric: string,
  change: number,
): "good" | "bad" | "neutral" {
  if (!LOWER_IS_BETTER.has(metric) || Math.abs(change) < 1e-9) return "neutral";
  return change < 0 ? "good" : "bad";
}

/** Hours as `{value, unit}` for the message catalogue. */
export function duration(hours: number): { value: number; unit: "h" | "d" } {
  return hours >= 48
    ? { value: Math.round((hours / 24) * 10) / 10, unit: "d" }
    : { value: Math.round(hours * 10) / 10, unit: "h" };
}
