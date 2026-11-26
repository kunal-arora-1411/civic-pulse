import { describe, expect, it } from "vitest";
import {
  DEFAULT_FILTERS,
  fromSavedFilters,
  isRangeInvalid,
  matchesSaved,
  parseFilters,
  resolvePeriod,
  serializeFilters,
  todayIst,
  toQuery,
  toSavedFilters,
} from "./filters";

describe("analytics filters", () => {
  it("round-trips through the URL and drops defaults", () => {
    const params = new URLSearchParams(
      "range=custom&from=2026-10-01&to=2026-10-31&ward=w1&status=resolved&status=bogus&interval=week",
    );
    const filters = parseFilters(params);
    expect(filters).toEqual({
      range: "custom",
      from: "2026-10-01",
      to: "2026-10-31",
      category: "",
      ward: "w1",
      status: ["resolved"],
      interval: "week",
    });
    expect(serializeFilters(filters).toString()).toBe(
      "range=custom&from=2026-10-01&to=2026-10-31&ward=w1&status=resolved&interval=week",
    );
    expect(serializeFilters(DEFAULT_FILTERS).toString()).toBe("");
  });

  it("resolves presets to inclusive IST days", () => {
    const today = "2026-11-24";
    const at = (range: (typeof DEFAULT_FILTERS)["range"]) =>
      resolvePeriod({ ...DEFAULT_FILTERS, range }, today);
    expect(at("7d")).toEqual({ from: "2026-11-18", to: today });
    expect(at("30d")).toEqual({ from: "2026-10-26", to: today });
    expect(at("90d")).toEqual({ from: "2026-08-27", to: today });
    expect(at("mtd")).toEqual({ from: "2026-11-01", to: today });
  });

  it("uses the India calendar day", () => {
    // 20:00 UTC is already the next day in IST.
    expect(todayIst(new Date("2026-11-23T20:00:00Z"))).toBe("2026-11-24");
  });

  it("builds the API query and flags an inverted range", () => {
    const filters = {
      ...DEFAULT_FILTERS,
      range: "custom" as const,
      from: "2026-11-10",
      to: "2026-11-01",
      category: "c1",
    };
    expect(isRangeInvalid(filters)).toBe(true);
    expect(toQuery({ ...filters, from: "2026-10-01" }, "2026-11-24")).toEqual({
      from: "2026-10-01",
      to: "2026-11-01",
      category_id: "c1",
      ward_id: undefined,
      status: undefined,
    });
  });
});

describe("saved filters", () => {
  it("converts to and from what a saved view stores", () => {
    const filters = parseFilters(
      new URLSearchParams(
        "range=custom&from=2026-10-01&to=2026-10-31&category=c1&status=resolved&interval=week",
      ),
    );
    const saved = toSavedFilters(filters);
    expect(saved).toEqual({
      range: "custom",
      from: "2026-10-01",
      to: "2026-10-31",
      category_id: "c1",
      ward_id: null,
      status: ["resolved"],
      interval: "week",
    });
    expect(fromSavedFilters(saved)).toEqual(filters);
    expect(matchesSaved(filters, saved)).toBe(true);
    expect(matchesSaved({ ...filters, ward: "w1" }, saved)).toBe(false);
  });

  it("keeps dates only for a custom range", () => {
    const saved = toSavedFilters({
      ...DEFAULT_FILTERS,
      range: "7d",
      from: "2026-10-01",
      to: "2026-10-31",
    });
    expect(saved.from).toBeNull();
    expect(saved.to).toBeNull();
  });
});
