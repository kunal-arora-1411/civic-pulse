/*
 * NEXT_PUBLIC_* values are inlined at build time, so they must be read with
 * a literal `process.env.NEXT_PUBLIC_…` expression (no destructuring).
 */
export const API_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
).replace(/\/+$/, "");

export const TENANT = process.env.NEXT_PUBLIC_TENANT || "demo-city";

export const API_BASE = `${API_URL}/api/v1`;
