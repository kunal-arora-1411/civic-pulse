import { describe, expect, it } from "vitest";
import {
  activeFilterCount,
  EMPTY_FILTERS,
  type IssueFilters,
  parseIssueFilters,
  serializeIssueFilters,
  toListParams,
  updateFilters,
} from "./filters";

const parse = (query: string) => parseIssueFilters(new URLSearchParams(query));

describe("issue filters in the URL", () => {
  it("round-trips every filter", () => {
    const filters: IssueFilters = {
      status: ["reported", "under_review"],
      category: ["cat-pothole", "cat-waste"],
      ward: ["w3"],
      severity: ["high", "critical"],
      band: ["critical"],
      overdue: true,
      from: "2026-11-01",
      to: "2026-11-24",
      q: "MG Road",
      sort: "-report_count",
      page: 3,
    };
    const query = serializeIssueFilters(filters).toString();
    expect(query).toBe(
      "q=MG+Road&status=reported&status=under_review&category=cat-pothole&category=cat-waste&ward=w3&severity=high&severity=critical&band=critical&overdue=1&from=2026-11-01&to=2026-11-24&sort=-report_count&page=3",
    );
    expect(parse(query)).toEqual(filters);
  });

  it("treats undefined as unset rather than writing it to the URL", () => {
    expect(
      serializeIssueFilters({
        status: ["verified"],
        sort: undefined,
      }).toString(),
    ).toBe("status=verified");
  });

  it("leaves defaults out of the URL", () => {
    expect(serializeIssueFilters(EMPTY_FILTERS).toString()).toBe("");
    expect(parse("")).toEqual(EMPTY_FILTERS);
  });

  it("round-trips a parsed URL to the same string", () => {
    const query = "status=verified&ward=w1&ward=w2&sort=created_at";
    expect(serializeIssueFilters(parse(query)).toString()).toBe(query);
  });

  it("drops values it doesn't recognise instead of failing", () => {
    expect(
      parse(
        "status=reported&status=bogus&sort=-hacked&page=-2&from=2026-02-30&to=yesterday&ward=a%20b&category=../x&severity=extreme&band=urgent",
      ),
    ).toEqual({ ...EMPTY_FILTERS, status: ["reported"] });
  });

  it("round-trips the severity and priority band filters on their own", () => {
    const query = "severity=low&band=high&band=medium";
    const filters = parse(query);
    expect(filters.severity).toEqual(["low"]);
    expect(filters.band).toEqual(["high", "medium"]);
    expect(serializeIssueFilters(filters).toString()).toBe(query);
    expect(toListParams(filters, 25)).toMatchObject({
      severity: ["low"],
      priority_band: ["high", "medium"],
      sort: "-priority",
    });
  });

  it("sorts by priority by default and keeps that out of the URL", () => {
    expect(parse("").sort).toBe("-priority");
    expect(
      serializeIssueFilters({ ...EMPTY_FILTERS, sort: "-priority" }).toString(),
    ).toBe("");
    expect(
      serializeIssueFilters({
        ...EMPTY_FILTERS,
        sort: "-created_at",
      }).toString(),
    ).toBe("sort=-created_at");
  });

  it("de-duplicates repeated values", () => {
    expect(parse("status=reported&status=reported").status).toEqual([
      "reported",
    ]);
  });

  it("goes back to page 1 when a filter changes, but not when paging", () => {
    const onPage3 = { ...EMPTY_FILTERS, page: 3 };
    expect(updateFilters(onPage3, { status: ["verified"] }).page).toBe(1);
    expect(updateFilters(onPage3, { page: 4 }).page).toBe(4);
  });

  it("counts active filters", () => {
    expect(
      activeFilterCount(parse("status=reported&status=verified&q=x")),
    ).toBe(3);
  });

  it("turns filters into API params with offset paging", () => {
    expect(toListParams(parse("status=reported&ward=w3&page=2"), 25)).toEqual({
      status: ["reported"],
      category_id: undefined,
      ward_id: ["w3"],
      severity: undefined,
      priority_band: undefined,
      from: undefined,
      to: undefined,
      q: undefined,
      sort: "-priority",
      limit: 25,
      offset: 25,
    });
  });

  it("doesn't send an inverted date range", () => {
    const params = toListParams(parse("from=2026-11-20&to=2026-11-01"), 25);
    expect(params.from).toBeUndefined();
    expect(params.to).toBeUndefined();
  });
});
