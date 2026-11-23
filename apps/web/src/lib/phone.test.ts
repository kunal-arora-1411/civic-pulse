import { describe, expect, it } from "vitest";
import {
  formatIndianPhone,
  maskIndianPhone,
  normalizeIndianPhone,
} from "./phone";

describe("normalizeIndianPhone", () => {
  it.each([
    ["9876543210", "+919876543210"],
    ["98765 43210", "+919876543210"],
    ["98765-43210", "+919876543210"],
    ["(987) 654-3210", "+919876543210"],
    ["09876543210", "+919876543210"],
    ["919876543210", "+919876543210"],
    ["+919876543210", "+919876543210"],
    ["+91 98765 43210", "+919876543210"],
    ["  6123456789  ", "+916123456789"],
    ["+91-9000000001", "+919000000001"],
  ])("normalises %j to %s", (input, expected) => {
    expect(normalizeIndianPhone(input)).toBe(expected);
  });

  it.each([
    [""],
    ["12345"],
    ["987654321"], // nine digits
    ["98765432101"], // eleven digits without a trunk zero
    ["5876543210"], // mobile numbers start with 6-9
    ["+14155552671"], // other country codes are not supported
    ["+9198765432"], // too short after +91
    ["98765abc10"],
    ["9876543210 ext 2"],
  ])("rejects %j", (input) => {
    expect(normalizeIndianPhone(input)).toBeNull();
  });
});

describe("formatIndianPhone", () => {
  it("groups the national number for readability", () => {
    expect(formatIndianPhone("+919876543210")).toBe("+91 98765 43210");
  });

  it("leaves unexpected values alone", () => {
    expect(formatIndianPhone("+14155552671")).toBe("+14155552671");
  });
});

describe("maskIndianPhone", () => {
  it("keeps only the last four digits", () => {
    expect(maskIndianPhone("+919876543210")).toBe("+91 ••••• •3210");
  });
});
