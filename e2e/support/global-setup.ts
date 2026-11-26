import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium, request } from "@playwright/test";
import { Api } from "./api";
import {
  API_URL,
  COMPOSE,
  PHOTO_PATH,
  SEEDED,
  STAFF_PATH,
  TENANT,
} from "./env";
import { type GeneratedStaff, STAFF_ROLES, type StaffKey } from "./staff";

const START_HINT = `Start it from the repo root with:\n  ${COMPOSE} up -d --build --wait`;
const SEED_HINT = `Seed it with:\n  ${COMPOSE} exec -T ai-worker python scripts/seed.py`;

const SEEDED_CATEGORIES = [
  "pothole",
  "waste",
  "waterlogging",
  "streetlight",
  "drainage",
];

class SetupError extends Error {
  override name = "E2E setup";
}

async function get(path: string, headers: Record<string, string> = {}) {
  try {
    return await fetch(`${API_URL}${path}`, {
      headers,
      signal: AbortSignal.timeout(10_000),
    });
  } catch (error) {
    throw new SetupError(
      `The API isn't reachable at ${API_URL} (${String(error)}).\n${START_HINT}`,
    );
  }
}

/** Fail fast, with a message that says what to do, if the stack isn't ready. */
async function checkStack() {
  const ready = await get("/ready");
  if (!ready.ok) {
    throw new SetupError(
      `The API at ${API_URL} is up but not ready (${ready.status}: ${await ready.text()}).\n${START_HINT}`,
    );
  }

  const tenant = await get("/api/v1/tenants/current", { "X-Tenant": TENANT });
  if (!tenant.ok) {
    throw new SetupError(
      `Tenant "${TENANT}" doesn't exist (${tenant.status}). The database hasn't been seeded.\n${SEED_HINT}`,
    );
  }
  const { map } = (await tenant.json()) as { map: unknown };
  if (!map) {
    throw new SetupError(
      `Tenant "${TENANT}" has no city boundary, so the Phase 1 seed hasn't run.\n${SEED_HINT}`,
    );
  }

  const categories = await get("/api/v1/categories", { "X-Tenant": TENANT });
  const codes = categories.ok
    ? ((await categories.json()) as { code: string }[]).map((c) => c.code)
    : [];
  const missing = SEEDED_CATEGORIES.filter((code) => !codes.includes(code));
  if (missing.length > 0) {
    throw new SetupError(
      `The seeded categories are missing (${missing.join(", ")}).\n${SEED_HINT}`,
    );
  }
}

/**
 * A real JPEG for the upload tests, drawn on a canvas by Chromium itself
 * so the suite needs no image tooling or committed binaries. It's big
 * enough (1280×960) that the browser-side compression has real work to do.
 */
async function generatePhoto() {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const dataUrl = await page.evaluate(() => {
      const canvas = document.createElement("canvas");
      canvas.width = 1280;
      canvas.height = 960;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("No 2D canvas");
      const sky = ctx.createLinearGradient(0, 0, 0, 400);
      sky.addColorStop(0, "#8ec5e8");
      sky.addColorStop(1, "#dcecf5");
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, 1280, 400);
      ctx.fillStyle = "#5b5f63";
      ctx.fillRect(0, 400, 1280, 560);
      ctx.fillStyle = "#f2f2f2";
      for (let x = 40; x < 1280; x += 220) ctx.fillRect(x, 660, 120, 18);
      ctx.fillStyle = "#2b2622";
      ctx.beginPath();
      ctx.ellipse(640, 800, 210, 70, 0, 0, Math.PI * 2);
      ctx.fill();
      // Noise, so the encoder can't squeeze the file down to nothing.
      for (let i = 0; i < 40_000; i++) {
        const shade = Math.floor(Math.random() * 255);
        ctx.fillStyle = `rgba(${shade},${shade},${shade},0.15)`;
        ctx.fillRect(Math.random() * 1280, 400 + Math.random() * 560, 3, 3);
      }
      ctx.fillStyle = "#1d1d1d";
      ctx.font = "bold 56px sans-serif";
      ctx.fillText("CivicPulse e2e: pothole", 48, 110);
      return canvas.toDataURL("image/jpeg", 0.9);
    });
    const bytes = Buffer.from(dataUrl.split(",")[1] ?? "", "base64");
    if (bytes[0] !== 0xff || bytes[1] !== 0xd8) {
      throw new SetupError("Chromium didn't produce a JPEG for the fixture.");
    }
    const path = fileURLToPath(PHOTO_PATH);
    await mkdir(fileURLToPath(new URL(".", PHOTO_PATH)), { recursive: true });
    await writeFile(path, bytes);
  } finally {
    await browser.close();
  }
}

/**
 * Fresh staff accounts for this run (support/staff.ts), made by the seeded
 * municipal admin, and which embedding model the stack is running.
 */
async function createStaff() {
  const context = await request.newContext();
  try {
    const api = new Api(context);
    const admin = await api.login(SEEDED.municipalAdmin);
    const phones = {} as Record<StaffKey, string>;
    for (const [key, role] of Object.entries(STAFF_ROLES)) {
      phones[key as StaffKey] = await api.createStaff(
        admin,
        role,
        `e2e ${key}`,
      );
    }
    const models = await api.aiModels(admin);
    const embedding = models.find(
      (model) => model.task === "embedding" && model.active,
    );
    const staff: GeneratedStaff = {
      phones,
      embeddingModel: embedding?.model_id ?? null,
    };
    const path = fileURLToPath(STAFF_PATH);
    await mkdir(fileURLToPath(new URL(".", STAFF_PATH)), { recursive: true });
    await writeFile(path, JSON.stringify(staff, null, 2));
  } finally {
    await context.dispose();
  }
}

export default async function globalSetup() {
  await checkStack();
  await generatePhoto();
  await createStaff();
}
