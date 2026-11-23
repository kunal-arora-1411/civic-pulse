import type { CategoryField, CategoryFieldType } from "@/lib/api";

/*
 * Editing a category's `fields` (the extra questions the report form asks
 * for that category). The editor works on drafts with a local id, so
 * React keys stay stable while keys and labels are being typed, and
 * converts to and from the API shape at the edges.
 */

export type DraftOption = { id: string; value: string; en: string; hi: string };

export type DraftField = {
  id: string;
  key: string;
  type: CategoryFieldType;
  required: boolean;
  en: string;
  hi: string;
  options: DraftOption[];
};

export const KEY_PATTERN = /^[a-z][a-z0-9_]{0,39}$/;
export const MAX_FIELDS = 10;
export const MAX_OPTIONS = 20;

let counter = 0;
export function localId(prefix = "f"): string {
  counter += 1;
  return `${prefix}${counter}-${Math.random().toString(36).slice(2, 7)}`;
}

/** "Pole number, if visible" → "pole_number_if_visible". */
export function slugifyKey(label: string): string {
  const slug = label
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 40);
  return /^[a-z]/.test(slug) ? slug : slug ? `f_${slug}`.slice(0, 40) : "";
}

export function newField(): DraftField {
  return {
    id: localId(),
    key: "",
    type: "text",
    required: false,
    en: "",
    hi: "",
    options: [],
  };
}

export function newOption(): DraftOption {
  return { id: localId("o"), value: "", en: "", hi: "" };
}

export function toDraftFields(fields: readonly CategoryField[]): DraftField[] {
  return fields.map((field) => ({
    id: localId(),
    key: field.key,
    type: field.type,
    required: field.required,
    en: field.label_i18n.en ?? "",
    hi: field.label_i18n.hi ?? "",
    options: (field.options ?? []).map((option) => ({
      id: localId("o"),
      value: option.value,
      en: option.label_i18n.en ?? "",
      hi: option.label_i18n.hi ?? "",
    })),
  }));
}

/** English is required; Hindi is left out rather than sent empty. */
export function toI18n(en: string, hi: string): Record<string, string> {
  const text: Record<string, string> = { en: en.trim() };
  if (hi.trim()) text.hi = hi.trim();
  return text;
}

export function fromDraftFields(
  fields: readonly DraftField[],
): CategoryField[] {
  return fields.map((field) => ({
    key: field.key.trim(),
    type: field.type,
    required: field.required,
    label_i18n: toI18n(field.en, field.hi),
    ...(field.type === "select"
      ? {
          options: field.options.map((option) => ({
            value: option.value.trim(),
            label_i18n: toI18n(option.en, option.hi),
          })),
        }
      : {}),
  }));
}

export type FieldError =
  | "key_required"
  | "key_format"
  | "key_duplicate"
  | "label_required"
  | "options_required"
  | "option_value_required"
  | "option_value_duplicate"
  | "option_label_required";

export type FieldErrors = Record<
  string,
  { field: FieldError[]; options: Record<string, FieldError[]> }
>;

/** Problems per draft field id; empty when everything is valid. */
export function validateFields(fields: readonly DraftField[]): FieldErrors {
  const errors: FieldErrors = {};
  const keyCounts = new Map<string, number>();
  for (const field of fields) {
    const key = field.key.trim();
    if (key) keyCounts.set(key, (keyCounts.get(key) ?? 0) + 1);
  }
  for (const field of fields) {
    const fieldErrors: FieldError[] = [];
    const optionErrors: Record<string, FieldError[]> = {};
    const key = field.key.trim();
    if (!key) fieldErrors.push("key_required");
    else if (!KEY_PATTERN.test(key)) fieldErrors.push("key_format");
    else if ((keyCounts.get(key) ?? 0) > 1) fieldErrors.push("key_duplicate");
    if (!field.en.trim()) fieldErrors.push("label_required");
    if (field.type === "select") {
      if (field.options.length === 0) fieldErrors.push("options_required");
      const valueCounts = new Map<string, number>();
      for (const option of field.options) {
        const value = option.value.trim();
        if (value) valueCounts.set(value, (valueCounts.get(value) ?? 0) + 1);
      }
      for (const option of field.options) {
        const problems: FieldError[] = [];
        const value = option.value.trim();
        if (!value) problems.push("option_value_required");
        else if ((valueCounts.get(value) ?? 0) > 1) {
          problems.push("option_value_duplicate");
        }
        if (!option.en.trim()) problems.push("option_label_required");
        if (problems.length) optionErrors[option.id] = problems;
      }
    }
    if (fieldErrors.length || Object.keys(optionErrors).length) {
      errors[field.id] = { field: fieldErrors, options: optionErrors };
    }
  }
  return errors;
}

export function hasFieldErrors(errors: FieldErrors): boolean {
  return Object.keys(errors).length > 0;
}

export function moveItem<T>(
  items: readonly T[],
  from: number,
  to: number,
): T[] {
  if (to < 0 || to >= items.length || from === to) return [...items];
  const next = [...items];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item as T);
  return next;
}
