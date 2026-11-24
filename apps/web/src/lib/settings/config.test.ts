import { describe, expect, it } from "vitest";
import {
  computePriority,
  DEFAULT_MATCHING_CONFIG,
  DEFAULT_PRIORITY_CONFIG,
  fromMatchingForm,
  fromPriorityForm,
  toForm,
  validateMatching,
  validatePriority,
} from "./config";

describe("matching settings", () => {
  const form = () => toForm(DEFAULT_MATCHING_CONFIG);

  it("accepts the defaults and round-trips them", () => {
    expect(validateMatching(form())).toEqual({});
    expect(fromMatchingForm(form())).toEqual(DEFAULT_MATCHING_CONFIG);
  });

  it("requires numbers between 0 and 1", () => {
    expect(
      validateMatching({ ...form(), "thresholds.auto": "1.2" }),
    ).toMatchObject({ "thresholds.auto": "range01" });
    expect(
      validateMatching({ ...form(), "thresholds.visual_min": "" }),
    ).toMatchObject({ "thresholds.visual_min": "number" });
  });

  it("requires the weights to add up to 1", () => {
    expect(validateMatching({ ...form(), "weights.geo": "0.5" })).toEqual({
      weights: "weightsSumOne",
    });
  });

  it("keeps the review threshold below the auto-link threshold", () => {
    expect(validateMatching({ ...form(), "thresholds.review": "0.9" })).toEqual(
      { "thresholds.review": "reviewBelowAuto" },
    );
  });
});

describe("priority settings", () => {
  const form = () => toForm(DEFAULT_PRIORITY_CONFIG);

  it("accepts the defaults and round-trips them", () => {
    expect(validatePriority(form())).toEqual({});
    expect(fromPriorityForm(form())).toEqual(DEFAULT_PRIORITY_CONFIG);
  });

  it("requires weights out of 100 that add up to 100", () => {
    expect(validatePriority({ ...form(), "weights.age": "120" })).toMatchObject(
      { "weights.age": "range100" },
    );
    expect(validatePriority({ ...form(), "weights.age": "20" })).toEqual({
      weights: "weightsSumHundred",
    });
  });

  it("requires severity points that rise with the level", () => {
    expect(
      validatePriority({ ...form(), "severity_points.high": "0.3" }),
    ).toMatchObject({ "severity_points.high": "pointsIncreasing" });
  });

  it("requires band thresholds that fall from critical to medium", () => {
    expect(validatePriority({ ...form(), "bands.high": "85" })).toMatchObject({
      "bands.high": "bandsDescending",
    });
    expect(
      validatePriority({ ...form(), reporters_saturation: "0" }),
    ).toMatchObject({ reporters_saturation: "atLeastOne" });
  });
});

describe("computePriority", () => {
  it("scores the contract's example factors and bands the total", () => {
    const result = computePriority(DEFAULT_PRIORITY_CONFIG, {
      severity: "high",
      uniqueReporters: 3,
      ageDays: 15,
      similarNearby: 0,
      nearPlace: true,
    });
    const points = Object.fromEntries(
      result.factors.map((f) => [f.factor, f.points]),
    );
    expect(points.severity).toBeCloseTo(30);
    expect(points.reporters).toBeCloseTo((20 * Math.log(4)) / Math.log(11));
    expect(points.age).toBeCloseTo(7.5);
    expect(points.near_places).toBe(10);
    expect(result.score).toBeCloseTo(59.06, 1);
    expect(result.band).toBe("medium");
    expect(result.factors[0].factor).toBe("severity");
  });

  it("caps each factor, so many reports alone can't max the score", () => {
    const result = computePriority(DEFAULT_PRIORITY_CONFIG, {
      severity: "low",
      uniqueReporters: 500,
      ageDays: 0,
      similarNearby: 0,
      nearPlace: false,
    });
    expect(result.score).toBeCloseTo(4 + 20);
    expect(result.band).toBe("low");
  });
});
