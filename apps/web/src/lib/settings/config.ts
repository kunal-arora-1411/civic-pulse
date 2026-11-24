import type {
  MatchingConfig,
  PriorityBand,
  PriorityConfig,
  SeverityLevel,
} from "@/lib/api";

/*
 * The matching and priority settings screens (Phase 2 contract D.2, F,
 * G): defaults, validation and the priority formula for the live
 * preview. The API validates again on save; these checks are here so the
 * form can say what's wrong next to the field before anything is sent.
 */

export const DEFAULT_MATCHING_CONFIG: MatchingConfig = {
  auto_link_enabled: true,
  weights: { geo: 0.4, visual: 0.4, category: 0.1, time: 0.1 },
  thresholds: { auto: 0.85, review: 0.6, visual_min: 0.8 },
  classification_threshold: 0.45,
  fallback_review_threshold: 0.4,
};

export const DEFAULT_PRIORITY_CONFIG: PriorityConfig = {
  weights: {
    severity: 40,
    reporters: 20,
    age: 15,
    recurrence: 15,
    near_places: 10,
  },
  severity_points: { low: 0.1, medium: 0.4, high: 0.75, critical: 1 },
  reporters_saturation: 10,
  age_saturation_days: 30,
  recurrence: { radius_m: 50, lookback_days: 180, saturation: 3 },
  bands: { critical: 80, high: 60, medium: 35 },
};

/** Form values are kept as typed, so a half-typed number isn't lost. */
export type FormValues = Record<string, string>;
/** Field path → message key (under the screen's `errors`). */
export type FormErrors = Record<string, string>;

/** Flatten a config to `a.b` paths with string values. */
export function toForm(config: object, prefix = ""): FormValues {
  const out: FormValues = {};
  for (const [key, value] of Object.entries(config)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object") {
      Object.assign(out, toForm(value, path));
    } else {
      out[path] = String(value);
    }
  }
  return out;
}

function num(values: FormValues, path: string): number {
  const raw = (values[path] ?? "").trim();
  return raw === "" ? Number.NaN : Number(raw);
}

function checkRange(
  values: FormValues,
  errors: FormErrors,
  path: string,
  min: number,
  max: number,
  options: { integer?: boolean; minExclusive?: boolean } = {},
) {
  const value = num(values, path);
  const rangeKey =
    max === Number.POSITIVE_INFINITY
      ? "atLeastOne"
      : max === 100
        ? "range100"
        : "range01";
  if (!Number.isFinite(value)) errors[path] = "number";
  else if (options.integer && !Number.isInteger(value))
    errors[path] = "integer";
  else if (options.minExclusive ? value <= min : value < min)
    errors[path] = rangeKey;
  else if (value > max) errors[path] = rangeKey;
}

const close = (a: number, b: number) => Math.abs(a - b) < 0.0005;

export const MATCHING_WEIGHTS = ["geo", "visual", "category", "time"] as const;

export function weightTotal(
  values: FormValues,
  keys: readonly string[],
): number {
  return keys.reduce(
    (sum, key) => sum + (num(values, `weights.${key}`) || 0),
    0,
  );
}

export function validateMatching(values: FormValues): FormErrors {
  const errors: FormErrors = {};
  for (const key of MATCHING_WEIGHTS) {
    checkRange(values, errors, `weights.${key}`, 0, 1);
  }
  if (
    MATCHING_WEIGHTS.every((key) => !errors[`weights.${key}`]) &&
    !close(weightTotal(values, MATCHING_WEIGHTS), 1)
  ) {
    errors.weights = "weightsSumOne";
  }
  for (const path of [
    "thresholds.auto",
    "thresholds.review",
    "thresholds.visual_min",
    "classification_threshold",
    "fallback_review_threshold",
  ]) {
    checkRange(values, errors, path, 0, 1);
  }
  if (
    !errors["thresholds.auto"] &&
    !errors["thresholds.review"] &&
    num(values, "thresholds.review") >= num(values, "thresholds.auto")
  ) {
    errors["thresholds.review"] = "reviewBelowAuto";
  }
  return errors;
}

export function fromMatchingForm(values: FormValues): MatchingConfig {
  return {
    auto_link_enabled: values.auto_link_enabled === "true",
    weights: {
      geo: num(values, "weights.geo"),
      visual: num(values, "weights.visual"),
      category: num(values, "weights.category"),
      time: num(values, "weights.time"),
    },
    thresholds: {
      auto: num(values, "thresholds.auto"),
      review: num(values, "thresholds.review"),
      visual_min: num(values, "thresholds.visual_min"),
    },
    classification_threshold: num(values, "classification_threshold"),
    fallback_review_threshold: num(values, "fallback_review_threshold"),
  };
}

export const PRIORITY_WEIGHTS = [
  "severity",
  "reporters",
  "age",
  "recurrence",
  "near_places",
] as const;
export type PriorityFactorKey = (typeof PRIORITY_WEIGHTS)[number];

export function validatePriority(values: FormValues): FormErrors {
  const errors: FormErrors = {};
  for (const key of PRIORITY_WEIGHTS) {
    checkRange(values, errors, `weights.${key}`, 0, 100);
  }
  if (
    PRIORITY_WEIGHTS.every((key) => !errors[`weights.${key}`]) &&
    !close(weightTotal(values, PRIORITY_WEIGHTS), 100)
  ) {
    errors.weights = "weightsSumHundred";
  }
  const levels: SeverityLevel[] = ["low", "medium", "high", "critical"];
  for (const level of levels) {
    checkRange(values, errors, `severity_points.${level}`, 0, 1);
  }
  for (let i = 1; i < levels.length; i++) {
    const path = `severity_points.${levels[i]}`;
    const below = `severity_points.${levels[i - 1]}`;
    if (
      !errors[path] &&
      !errors[below] &&
      num(values, path) < num(values, below)
    ) {
      errors[path] = "pointsIncreasing";
    }
  }
  for (const path of [
    "reporters_saturation",
    "age_saturation_days",
    "recurrence.radius_m",
    "recurrence.lookback_days",
    "recurrence.saturation",
  ]) {
    checkRange(values, errors, path, 1, Number.POSITIVE_INFINITY);
  }
  for (const band of ["critical", "high", "medium"]) {
    checkRange(values, errors, `bands.${band}`, 0, 100, { minExclusive: true });
  }
  const c = num(values, "bands.critical");
  const h = num(values, "bands.high");
  const m = num(values, "bands.medium");
  if (!errors["bands.high"] && !errors["bands.critical"] && h >= c) {
    errors["bands.high"] = "bandsDescending";
  }
  if (!errors["bands.medium"] && !errors["bands.high"] && m >= h) {
    errors["bands.medium"] = "bandsDescending";
  }
  return errors;
}

export function fromPriorityForm(values: FormValues): PriorityConfig {
  return {
    weights: {
      severity: num(values, "weights.severity"),
      reporters: num(values, "weights.reporters"),
      age: num(values, "weights.age"),
      recurrence: num(values, "weights.recurrence"),
      near_places: num(values, "weights.near_places"),
    },
    severity_points: {
      low: num(values, "severity_points.low"),
      medium: num(values, "severity_points.medium"),
      high: num(values, "severity_points.high"),
      critical: num(values, "severity_points.critical"),
    },
    reporters_saturation: num(values, "reporters_saturation"),
    age_saturation_days: num(values, "age_saturation_days"),
    recurrence: {
      radius_m: num(values, "recurrence.radius_m"),
      lookback_days: num(values, "recurrence.lookback_days"),
      saturation: num(values, "recurrence.saturation"),
    },
    bands: {
      critical: num(values, "bands.critical"),
      high: num(values, "bands.high"),
      medium: num(values, "bands.medium"),
    },
  };
}

export type ExampleIssue = {
  severity: SeverityLevel;
  uniqueReporters: number;
  ageDays: number;
  /** Similar issues nearby within the lookback window. */
  similarNearby: number;
  nearPlace: boolean;
};

export type PreviewFactor = {
  factor: PriorityFactorKey;
  normalized: number;
  points: number;
};

/**
 * The priority formula (contract F), for the preview: each factor
 * normalised to [0, 1] and multiplied by its weight, summed to a score
 * out of 100, then banded. Reporter count is logarithmic, so volume alone
 * can't push an issue up (PRD §12.3).
 */
export function computePriority(
  config: PriorityConfig,
  example: ExampleIssue,
): { score: number; band: PriorityBand; factors: PreviewFactor[] } {
  const normalized: Record<PriorityFactorKey, number> = {
    severity: config.severity_points[example.severity],
    reporters: Math.min(
      1,
      Math.log(1 + Math.max(0, example.uniqueReporters)) /
        Math.log(1 + config.reporters_saturation),
    ),
    age: Math.min(1, Math.max(0, example.ageDays) / config.age_saturation_days),
    recurrence: Math.min(
      1,
      Math.max(0, example.similarNearby) / config.recurrence.saturation,
    ),
    near_places: example.nearPlace ? 1 : 0,
  };
  const factors = PRIORITY_WEIGHTS.map((factor) => ({
    factor,
    normalized: normalized[factor],
    points: normalized[factor] * config.weights[factor],
  })).sort((a, b) => b.points - a.points);
  const score = factors.reduce((sum, item) => sum + item.points, 0);
  const band: PriorityBand =
    score >= config.bands.critical
      ? "critical"
      : score >= config.bands.high
        ? "high"
        : score >= config.bands.medium
          ? "medium"
          : "low";
  return { score, band, factors };
}
