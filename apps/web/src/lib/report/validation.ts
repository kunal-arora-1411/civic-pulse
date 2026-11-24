import type { Category, CategoryField, CreateReportBody } from "@/lib/api";
import type { DraftLocation, ReportDraft } from "./draft";

/*
 * Step validation for the report flow. Pure functions, so the rules are
 * tested without rendering anything; the API re-checks all of them.
 */

/** Used for the photo step until a category (with its own rule) is chosen. */
export const DEFAULT_MAX_PHOTOS = 5;
/** GPS fixes worse than this need the citizen to confirm the pin. */
export const LOW_ACCURACY_M = 50;
export const DESCRIPTION_MAX = 2000;
/** Deployment policy: at least one photo or a description this long. */
export const DESCRIPTION_MIN_WITHOUT_PHOTO = 10;

export type PhotoStatus =
  | "preparing"
  | "uploading"
  | "verifying"
  | "done"
  | "error";

export type PhotoLimits = { min: number; max: number };

/**
 * The photo rule to apply. Before a category is chosen we ask for at
 * least one photo and allow up to the largest maximum of any category, so
 * nobody adds a sixth photo only to be told to remove it later. Once a
 * category is chosen its own min/max applies.
 */
export function photoLimits(
  category: Pick<Category, "evidence"> | null | undefined,
  categories: readonly Pick<Category, "evidence">[] = [],
): PhotoLimits {
  if (category) {
    return {
      min: category.evidence.min_photos,
      max: category.evidence.max_photos,
    };
  }
  const largest = Math.max(0, ...categories.map((c) => c.evidence.max_photos));
  return { min: 1, max: largest || DEFAULT_MAX_PHOTOS };
}

export type PhotoIssue = "too_few" | "too_many";

export function validatePhotoCount(
  count: number,
  limits: PhotoLimits,
): PhotoIssue | null {
  if (count < limits.min) return "too_few";
  if (count > limits.max) return "too_many";
  return null;
}

export type UploadState = "ready" | "uploading" | "failed";

/** Whether every photo has a media id we can submit. */
export function uploadState(
  photos: readonly { status: PhotoStatus }[],
): UploadState {
  if (photos.some((photo) => photo.status === "error")) return "failed";
  if (photos.some((photo) => photo.status !== "done")) return "uploading";
  return "ready";
}

export type GeoCheck =
  | { status: "pending" }
  /** The lookup failed; the server still checks on submit. */
  | { status: "unavailable" }
  | { status: "done"; inJurisdiction: boolean };

export type LocationIssue =
  | "missing"
  | "checking"
  | "out_of_jurisdiction"
  | "confirm_accuracy";

export function needsAccuracyConfirmation(location: DraftLocation): boolean {
  return (
    location.source === "gps" &&
    location.accuracyM !== null &&
    location.accuracyM > LOW_ACCURACY_M &&
    !location.accuracyConfirmed
  );
}

export function validateLocation(
  location: DraftLocation | null,
  geo: GeoCheck,
): LocationIssue | null {
  if (!location) return "missing";
  if (geo.status === "pending") return "checking";
  if (geo.status === "done" && !geo.inJurisdiction) {
    return "out_of_jurisdiction";
  }
  if (needsAccuracyConfirmation(location)) return "confirm_accuracy";
  return null;
}

export type FieldIssue = "required" | "number" | "option";

export type DetailsIssues = {
  category?: "required";
  photos?: PhotoIssue;
  description?: "too_long" | "too_short";
  fields: Record<string, FieldIssue>;
};

function isBlank(value: string | boolean | undefined): boolean {
  return value === undefined || (typeof value === "string" && !value.trim());
}

export function validateField(
  field: CategoryField,
  value: string | boolean | undefined,
): FieldIssue | null {
  if (isBlank(value)) return field.required ? "required" : null;
  if (field.type === "number") {
    return Number.isFinite(Number(String(value).trim())) ? null : "number";
  }
  if (field.type === "select") {
    const options = field.options ?? [];
    return options.some((option) => option.value === value) ? null : "option";
  }
  return null;
}

/** Step 3: category, its fields, the description, and the photo rule. */
export function validateDetails(
  category: Category | null | undefined,
  draft: Pick<ReportDraft, "details" | "description">,
  photoCount: number,
): DetailsIssues {
  const issues: DetailsIssues = { fields: {} };
  const description = draft.description.trim();
  if (description.length > DESCRIPTION_MAX) issues.description = "too_long";
  if (!category) {
    issues.category = "required";
    return issues;
  }
  const photos = validatePhotoCount(photoCount, photoLimits(category));
  if (photos) issues.photos = photos;
  if (
    photoCount === 0 &&
    description.length < DESCRIPTION_MIN_WITHOUT_PHOTO &&
    !issues.description
  ) {
    issues.description = "too_short";
  }
  for (const field of category.fields) {
    const issue = validateField(field, draft.details[field.key]);
    if (issue) issues.fields[field.key] = issue;
  }
  return issues;
}

export function hasDetailsIssues(issues: DetailsIssues): boolean {
  return Boolean(
    issues.category ||
      issues.photos ||
      issues.description ||
      Object.keys(issues.fields).length,
  );
}

/** Typed `details` for the API: numbers as numbers, blanks left out. */
export function buildDetails(
  category: Pick<Category, "fields">,
  details: ReportDraft["details"],
): CreateReportBody["details"] {
  const out: CreateReportBody["details"] = {};
  for (const field of category.fields) {
    const value = details[field.key];
    if (isBlank(value)) continue;
    if (field.type === "number") out[field.key] = Number(String(value).trim());
    else if (field.type === "boolean") out[field.key] = value === true;
    else out[field.key] = String(value).trim();
  }
  return out;
}

export function buildReportBody(
  draft: ReportDraft,
  category: Category,
  mediaIds: string[],
  now: Date = new Date(),
): CreateReportBody {
  if (!draft.location) throw new Error("A report needs a location");
  const { lat, lng, accuracyM, source } = draft.location;
  return {
    category_id: category.id,
    description: draft.description.trim(),
    location: { lat, lng, accuracy_m: accuracyM, source },
    ...(draft.addressText ? { address_text: draft.addressText } : {}),
    details: buildDetails(category, draft.details),
    media_ids: mediaIds,
    client_created_at: now.toISOString(),
    ...(draft.classificationId
      ? { classification_id: draft.classificationId }
      : {}),
  };
}
