/** Where the stack is. The defaults match infra/docker-compose.yml and `pnpm dev`. */
export const API_URL = (
  process.env.E2E_API_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");
export const WEB_URL = (
  process.env.E2E_WEB_URL ?? "http://localhost:3000"
).replace(/\/+$/, "");
export const TENANT = process.env.E2E_TENANT ?? "demo-city";

/** The dev OTP accepted when the API runs with DEV_FIXED_OTP=true. */
export const DEV_OTP = "000000";

/**
 * Seeded accounts (docs/api/phase-0-contract.md, "Seed data"). Each one is
 * used by a single test: an OTP request starts a 30-second per-phone
 * cooldown, so two tests signing in the same number in parallel would
 * race for it. Everything else signs in with a fresh citizen number.
 */
export const SEEDED = {
  municipalAdmin: "+919000000001", // console.spec.ts
  operator: "+919000000002", // staff.spec.ts
  supervisor: "+919000000003", // map.spec.ts
  citizen: "+919000000005", // report.spec.ts (AC-01)
} as const;

/**
 * A point inside Synthetic Ward 2 of the seeded city, and one well outside
 * the city (whose bounds are roughly lng 77.55–77.63, lat 12.93–13.01).
 */
export const INSIDE = { latitude: 12.9716, longitude: 77.5946 } as const;
export const OUTSIDE = { latitude: 12.85, longitude: 77.45 } as const;
export const INSIDE_WARD = "Synthetic Ward 2";

/** Where global setup writes the generated photo. */
export const PHOTO_PATH = new URL("../.generated/street.jpg", import.meta.url);
