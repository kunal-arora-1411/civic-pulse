import type { MatchSignals } from "@/lib/api";

/*
 * Arithmetic behind the match explanation (Phase 2 contract D.2–D.3),
 * kept apart from the component so the numbers are tested on their own.
 */

export const SIGNAL_KEYS = ["geo", "visual", "category", "time"] as const;
export type SignalKey = (typeof SIGNAL_KEYS)[number];

export type SignalRow = {
  key: SignalKey;
  /** 0–1, or null when the signal wasn't available (visual only). */
  value: number | null;
  /** The weight actually applied, after re-normalising for a missing signal. */
  weight: number;
  /** weight × value: what this signal added to the score. */
  points: number;
};

/**
 * Each signal with its effective weight and contribution. When there was
 * no photo comparison the visual weight is dropped and the others are
 * scaled up to sum to the same total, as the backend does.
 */
export function signalRows(signals: MatchSignals): SignalRow[] {
  const visualMissing = signals.visual === null;
  const total = SIGNAL_KEYS.reduce(
    (sum, key) =>
      key === "visual" && visualMissing ? sum : sum + signals.weights[key],
    0,
  );
  const fullTotal = SIGNAL_KEYS.reduce(
    (sum, key) => sum + signals.weights[key],
    0,
  );
  const scale = total > 0 ? fullTotal / total : 1;
  return SIGNAL_KEYS.map((key) => {
    const value = key === "visual" ? signals.visual : signals[key];
    const weight =
      key === "visual" && visualMissing ? 0 : signals.weights[key] * scale;
    return { key, value, weight, points: value === null ? 0 : value * weight };
  });
}

export type MatchVerdict =
  /** Passes every auto-link check. */
  | { kind: "auto" }
  /** Scores high enough to auto-link but fails another check. */
  | { kind: "auto_blocked"; why: "visual" | "distance" | "no_visual" }
  | { kind: "review" }
  | { kind: "low" };

/**
 * How the score compares with the thresholds, using the decision rules:
 * auto-link needs the score, the visual minimum and the radius; distance
 * alone never links (AC-05).
 */
export function matchVerdict(
  score: number,
  signals: MatchSignals,
): MatchVerdict {
  const { auto, review, visual_min } = signals.thresholds;
  if (score >= auto) {
    if (signals.visual === null)
      return { kind: "auto_blocked", why: "no_visual" };
    if (signals.visual < visual_min)
      return { kind: "auto_blocked", why: "visual" };
    if (signals.distance_m > signals.radius_m)
      return { kind: "auto_blocked", why: "distance" };
    return { kind: "auto" };
  }
  return score >= review ? { kind: "review" } : { kind: "low" };
}

/** Clamp to [0, 1] for drawing; the numbers shown are never clamped. */
export function unit(value: number): number {
  return Math.min(1, Math.max(0, value));
}
