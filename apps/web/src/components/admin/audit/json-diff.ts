function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Top-level keys whose values differ between `before` and `after`. Good
 * enough to point a reviewer at what changed; the full JSON is shown
 * alongside for anything nested.
 */
export function changedKeys(before: unknown, after: unknown): string[] {
  const a = isPlainObject(before) ? before : {};
  const b = isPlainObject(after) ? after : {};
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  return [...keys]
    .filter((key) => JSON.stringify(a[key]) !== JSON.stringify(b[key]))
    .sort();
}

export function prettyJson(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return JSON.stringify(value, null, 2);
}
