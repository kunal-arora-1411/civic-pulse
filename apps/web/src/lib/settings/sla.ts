import {
  PRIORITY_BANDS,
  type PriorityBand,
  type SlaTargetIn,
  type SlaTargets,
} from "@/lib/api";
import type { FormErrors, FormValues } from "./config";

/*
 * The SLA targets screen edits one row per category: a resolution target
 * for every band, optional narrower targets per band, and when to escalate
 * to the municipal admins. The API stores them as a flat list of targets
 * (docs/api/sla-escalation.md); these helpers convert between the two.
 */

export const SLA_COLUMNS = ["any", ...PRIORITY_BANDS, "escalate"] as const;
export type SlaColumn = (typeof SLA_COLUMNS)[number];
export type SlaRow = Partial<Record<SlaColumn, number>>;
/** Category id → its row. */
export type SlaDoc = Record<string, SlaRow>;

export const MAX_HOURS = 8760;

export function toSlaDoc(targets: SlaTargets): SlaDoc {
  const doc: SlaDoc = {};
  for (const target of targets.items) {
    const row = doc[target.category_id] ?? {};
    row[target.priority_band ?? "any"] = target.resolve_hours;
    // Every target of a category escalates after the same time here; the
    // category-wide one wins if the API holds different values.
    if (row.escalate === undefined || target.priority_band === null) {
      row.escalate = target.escalate_after_hours;
    }
    doc[target.category_id] = row;
  }
  return doc;
}

export function fromSlaDoc(doc: SlaDoc): SlaTargetIn[] {
  const items: SlaTargetIn[] = [];
  for (const [categoryId, row] of Object.entries(doc)) {
    if (row.escalate === undefined) continue;
    const bands: (PriorityBand | null)[] = [null, ...PRIORITY_BANDS];
    for (const band of bands) {
      const hours = row[band ?? "any"];
      if (hours === undefined) continue;
      items.push({
        category_id: categoryId,
        priority_band: band,
        resolve_hours: hours,
        escalate_after_hours: row.escalate,
      });
    }
  }
  return items;
}

function split(path: string): [string, SlaColumn] | null {
  const dot = path.lastIndexOf(".");
  const column = path.slice(dot + 1) as SlaColumn;
  if (dot < 1 || !SLA_COLUMNS.includes(column)) return null;
  return [path.slice(0, dot), column];
}

/** Form values (`<category id>.<column>`) back to a document. Blank cells are left out. */
export function fromSlaForm(values: FormValues): SlaDoc {
  const doc: SlaDoc = {};
  for (const [path, value] of Object.entries(values)) {
    const parts = split(path);
    if (!parts || value.trim() === "") continue;
    const [categoryId, column] = parts;
    doc[categoryId] = { ...doc[categoryId], [column]: Number(value) };
  }
  // A category with no target at all needs no escalation time.
  for (const [categoryId, row] of Object.entries(doc)) {
    if (Object.keys(row).every((key) => key === "escalate")) {
      delete doc[categoryId];
    }
  }
  return doc;
}

export function validateSla(values: FormValues): FormErrors {
  const errors: FormErrors = {};
  const withTarget = new Set<string>();
  const withEscalation = new Set<string>();
  for (const [path, value] of Object.entries(values)) {
    const parts = split(path);
    if (!parts || value.trim() === "") continue;
    const [categoryId, column] = parts;
    const hours = Number(value);
    if (!Number.isInteger(hours) || hours < 1 || hours > MAX_HOURS) {
      errors[path] = "hoursRange";
    }
    if (column === "escalate") withEscalation.add(categoryId);
    else withTarget.add(categoryId);
  }
  for (const categoryId of withTarget) {
    if (!withEscalation.has(categoryId)) {
      errors[`${categoryId}.escalate`] = "escalateRequired";
    }
  }
  return errors;
}
