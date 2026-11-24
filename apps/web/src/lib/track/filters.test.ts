import { describe, expect, it } from "vitest";
import {
  DEFAULT_TRACK_FILTERS,
  isFiltered,
  OPEN_STATUSES,
  PUBLIC_STATUSES,
  toQuery,
} from "./filters";

describe("public tracker filters", () => {
  it("sends nothing for the defaults", () => {
    expect(toQuery(DEFAULT_TRACK_FILTERS)).toEqual({
      status: undefined,
      category_id: undefined,
      ward_id: undefined,
    });
    expect(isFiltered(DEFAULT_TRACK_FILTERS)).toBe(false);
  });

  it("expands 'open' to every status still waiting for a fix", () => {
    const query = toQuery({ ...DEFAULT_TRACK_FILTERS, status: "open" });
    expect(query.status).toEqual(OPEN_STATUSES);
    expect(query.status).not.toContain("resolved");
    expect(query.status).not.toContain("closed");
    expect(PUBLIC_STATUSES).not.toContain("rejected");
  });

  it("passes one status, a category and a ward through", () => {
    const filters = {
      ...DEFAULT_TRACK_FILTERS,
      status: "resolved" as const,
      category_id: "cat-1",
      ward_id: "ward-3",
    };
    expect(toQuery(filters)).toEqual({
      status: ["resolved"],
      category_id: "cat-1",
      ward_id: "ward-3",
    });
    expect(isFiltered(filters)).toBe(true);
  });
});
