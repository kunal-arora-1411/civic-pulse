import { describe, expect, it } from "vitest";
import { isoToIstInput, istInputFromNow, istInputToIso } from "./announcements";

describe("announcement times", () => {
  it("reads a datetime-local value as India time", () => {
    expect(istInputToIso("2026-11-26T18:00")).toBe("2026-11-26T12:30:00.000Z");
    expect(istInputToIso("2026-11-26")).toBeNull();
    expect(istInputToIso("")).toBeNull();
  });

  it("shows an instant in India time", () => {
    expect(isoToIstInput("2026-11-26T20:00:00Z")).toBe("2026-11-27T01:30");
    expect(isoToIstInput("not a date")).toBe("");
  });

  it("round-trips and offsets from now", () => {
    const now = new Date("2026-11-26T00:00:00Z");
    expect(istInputFromNow(24, now)).toBe("2026-11-27T05:30");
    expect(istInputToIso(isoToIstInput("2026-11-26T09:15:00Z"))).toBe(
      "2026-11-26T09:15:00.000Z",
    );
  });
});
