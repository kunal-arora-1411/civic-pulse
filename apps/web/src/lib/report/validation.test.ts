import { describe, expect, it } from "vitest";
import type { Category } from "@/lib/api";
import { makeCategory } from "@/test/fixtures";
import { type DraftLocation, newDraft } from "./draft";
import {
  buildReportBody,
  hasDetailsIssues,
  photoLimits,
  uploadState,
  validateDetails,
  validateLocation,
  validatePhotoCount,
} from "./validation";

const pothole = makeCategory({
  evidence: { min_photos: 1, max_photos: 3 },
  fields: [
    {
      key: "size",
      type: "select",
      required: true,
      label_i18n: { en: "Size" },
      options: [
        { value: "small", label_i18n: { en: "Small" } },
        { value: "large", label_i18n: { en: "Large" } },
      ],
    },
    {
      key: "depth_cm",
      type: "number",
      required: false,
      label_i18n: { en: "Depth (cm)" },
    },
    {
      key: "blocking",
      type: "boolean",
      required: false,
      label_i18n: { en: "Blocking traffic" },
    },
    {
      key: "road_name",
      type: "text",
      required: false,
      label_i18n: { en: "Road" },
    },
  ],
});
const streetlight = makeCategory({
  id: "cat-light",
  code: "streetlight",
  evidence: { min_photos: 0, max_photos: 8 },
  fields: [],
});

describe("photo limits", () => {
  it("asks for 1 photo and the largest category maximum before a category is chosen", () => {
    expect(photoLimits(null, [pothole, streetlight])).toEqual({
      min: 1,
      max: 8,
    });
    expect(photoLimits(null, [])).toEqual({ min: 1, max: 5 });
  });

  it("uses the chosen category's own rule", () => {
    expect(photoLimits(pothole, [pothole, streetlight])).toEqual({
      min: 1,
      max: 3,
    });
  });

  it("flags too few and too many", () => {
    expect(validatePhotoCount(0, { min: 1, max: 3 })).toBe("too_few");
    expect(validatePhotoCount(1, { min: 1, max: 3 })).toBeNull();
    expect(validatePhotoCount(3, { min: 1, max: 3 })).toBeNull();
    expect(validatePhotoCount(4, { min: 1, max: 3 })).toBe("too_many");
  });

  it("re-checks the count once the category is known", () => {
    // Five photos were fine on step 1 (max 8), but potholes allow 3.
    const issues = validateDetails(
      pothole,
      { details: { size: "large" }, description: "" },
      5,
    );
    expect(issues.photos).toBe("too_many");
    expect(hasDetailsIssues(issues)).toBe(true);
  });

  it("knows when every upload has finished", () => {
    expect(uploadState([{ status: "done" }, { status: "done" }])).toBe("ready");
    expect(uploadState([{ status: "done" }, { status: "uploading" }])).toBe(
      "uploading",
    );
    expect(uploadState([{ status: "error" }, { status: "uploading" }])).toBe(
      "failed",
    );
  });
});

describe("validateLocation", () => {
  const gps = (accuracyM: number, confirmed = false): DraftLocation => ({
    lat: 12.97,
    lng: 77.59,
    accuracyM,
    source: "gps",
    accuracyConfirmed: confirmed,
  });

  it("needs a pin", () => {
    expect(validateLocation(null, { status: "pending" })).toBe("missing");
  });

  it("waits for the jurisdiction check", () => {
    expect(validateLocation(gps(10), { status: "pending" })).toBe("checking");
  });

  it("blocks points outside the city", () => {
    expect(
      validateLocation(gps(10), { status: "done", inJurisdiction: false }),
    ).toBe("out_of_jurisdiction");
  });

  it("lets the citizen continue if the lookup itself failed", () => {
    expect(validateLocation(gps(10), { status: "unavailable" })).toBeNull();
  });

  it("asks to confirm an imprecise GPS fix, but not a placed pin", () => {
    const inside = { status: "done", inJurisdiction: true } as const;
    expect(validateLocation(gps(120), inside)).toBe("confirm_accuracy");
    expect(validateLocation(gps(120, true), inside)).toBeNull();
    expect(validateLocation(gps(12), inside)).toBeNull();
    expect(
      validateLocation(
        { lat: 1, lng: 2, accuracyM: null, source: "pin" },
        inside,
      ),
    ).toBeNull();
  });
});

describe("validateDetails", () => {
  it("requires a category", () => {
    expect(validateDetails(null, newDraft(), 1).category).toBe("required");
  });

  it("checks required, number and select fields", () => {
    const issues = validateDetails(
      pothole,
      { details: { depth_cm: "deep", size: "huge" }, description: "" },
      1,
    );
    expect(issues.fields).toEqual({ depth_cm: "number", size: "option" });

    const missing = validateDetails(
      pothole,
      { details: {}, description: "" },
      1,
    );
    expect(missing.fields).toEqual({ size: "required" });

    const ok = validateDetails(
      pothole,
      {
        details: { size: "large", depth_cm: "12.5", blocking: false },
        description: "",
      },
      1,
    );
    expect(hasDetailsIssues(ok)).toBe(false);
  });

  it("limits the description to 2000 characters", () => {
    const issues = validateDetails(
      streetlight,
      { details: {}, description: "x".repeat(2001) },
      1,
    );
    expect(issues.description).toBe("too_long");
  });

  it("needs 10 characters of description when there's no photo", () => {
    expect(
      validateDetails(streetlight, { details: {}, description: "dark" }, 0)
        .description,
    ).toBe("too_short");
    expect(
      validateDetails(
        streetlight,
        { details: {}, description: "Light out for a week" },
        0,
      ).description,
    ).toBeUndefined();
  });
});

describe("buildReportBody", () => {
  it("sends typed details, the location provenance and the media ids", () => {
    const draft = {
      ...newDraft(),
      categoryId: pothole.id,
      description: "  Deep pothole near the bus stop  ",
      location: {
        lat: 12.9716,
        lng: 77.5946,
        accuracyM: 12,
        source: "gps" as const,
      },
      addressText: "MG Road",
      details: {
        size: "large",
        depth_cm: "15",
        blocking: true,
        road_name: "  ",
      },
    };
    const body = buildReportBody(
      draft,
      pothole as Category,
      ["m1", "m2"],
      new Date("2026-11-24T02:45:00Z"),
    );
    expect(body).toEqual({
      category_id: pothole.id,
      description: "Deep pothole near the bus stop",
      location: { lat: 12.9716, lng: 77.5946, accuracy_m: 12, source: "gps" },
      address_text: "MG Road",
      details: { size: "large", depth_cm: 15, blocking: true },
      media_ids: ["m1", "m2"],
      client_created_at: "2026-11-24T02:45:00.000Z",
    });
  });
});
