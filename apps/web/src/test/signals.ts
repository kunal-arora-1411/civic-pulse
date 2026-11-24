import type { MatchSignals } from "@/lib/api/schemas-ai";

/** The contract's example signals (D.3), with overrides. */
export function makeSignals(
  overrides: Partial<MatchSignals> = {},
): MatchSignals {
  return {
    distance_m: 18.4,
    radius_m: 30,
    geo: 0.54,
    visual: 0.91,
    same_photo: false,
    category: 1,
    time: 0.93,
    age_days: 2.1,
    weights: { geo: 0.4, visual: 0.4, category: 0.1, time: 0.1 },
    thresholds: { auto: 0.85, review: 0.6, visual_min: 0.8 },
    reason: null,
    ...overrides,
  };
}
