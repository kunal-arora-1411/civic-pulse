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
  municipalAdmin: "+919000000001", // global setup (makes the run's staff)
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

/**
 * A random point in the tenant's second, West Delhi area, which the seed
 * leaves empty. Matching compares a report with every issue within the
 * category's radius (30 m), so tests that care what a report matches put
 * it somewhere nothing else is: an earlier run's issue at the same spot
 * would otherwise be a candidate. The box is ~8 × 6 km, so two random
 * spots land within 30 m of each other about once in 20 000 tries.
 */
export function freshSpot(): { lat: number; lng: number } {
  // 77.10–77.16 E, 28.63–28.67 N: inside the area with a margin.
  return {
    lat: 28.63 + Math.random() * 0.04,
    lng: 77.1 + Math.random() * 0.06,
  };
}

/** A point `metres` east of `spot` (good enough at these distances). */
export function eastOf(
  spot: { lat: number; lng: number },
  metres: number,
): { lat: number; lng: number } {
  const perDegree = 111_320 * Math.cos((spot.lat * Math.PI) / 180);
  return { lat: spot.lat, lng: spot.lng + metres / perDegree };
}

/**
 * Openly licensed photos of real potholes (see fixtures/README.md), for
 * the tests that run the real vision model.
 */
export const POTHOLE_PHOTO = new URL(
  "../fixtures/pothole-villeray.jpg",
  import.meta.url,
);
export const OTHER_POTHOLE_PHOTO = new URL(
  "../fixtures/pothole-monaghan.jpg",
  import.meta.url,
);

/** Staff accounts made for this run by global setup (see staff.ts). */
export const STAFF_PATH = new URL("../.generated/staff.json", import.meta.url);

/**
 * How to reach the compose stack from the repo root, for the test that
 * stops the AI worker. Point it at another project or env file when the
 * stack runs under a different name.
 */
export const COMPOSE =
  process.env.E2E_COMPOSE ?? "docker compose -f infra/docker-compose.yml";
