import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { freshCitizenPhone } from "../support/api";
import {
  INSIDE,
  INSIDE_WARD,
  OUTSIDE,
  PHOTO_PATH,
  SEEDED,
} from "../support/env";
import { expect, giveSession, PHONE, test } from "../support/fixtures";
import { referenceYear, signInThroughUi } from "../support/ui";

/*
 * The citizen report flow on a phone (AC-01), plus the two ways it must
 * refuse or absorb trouble: a location outside the city, and a submission
 * whose response never arrives.
 */

test.use({
  ...PHONE,
  permissions: ["geolocation"],
  geolocation: { ...INSIDE, accuracy: 10 },
});

const continueButton = (page: Page) =>
  page.getByRole("button", { name: "Continue" });

async function addPhoto(page: Page) {
  await expect(
    page.getByRole("heading", { name: "Add photos of the problem" }),
  ).toBeVisible();
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Choose from gallery" }).click();
  await (await chooser).setFiles(fileURLToPath(PHOTO_PATH));
  // Compression, the pre-signed PUT to MinIO and server-side verification
  // all have to succeed before the tile says "Uploaded".
  await expect(page.getByText("1 of 1 uploaded")).toBeVisible({
    timeout: 30_000,
  });
}

async function locateWithGps(page: Page) {
  await expect(
    page.getByRole("heading", { name: "Where is the problem?" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Use my location" }).click();
  await expect(
    page.getByText(/Location found, accurate to ±10 m/),
  ).toBeVisible();
}

/** The address and ward card, once the lookup has finished. */
function locationFacts(page: Page) {
  const facts = page.locator("dl").filter({ hasText: "Address" });
  return {
    address: facts.locator("dt:text-is('Address') + dd"),
    ward: facts.locator("dt:text-is('Ward') + dd"),
  };
}

async function choosePothole(page: Page, description: string) {
  await expect(
    page.getByRole("heading", { name: "What kind of problem is it?" }),
  ).toBeVisible();
  await page.getByText("Pothole / road damage", { exact: true }).click();
  await expect(
    page.getByRole("radio", { name: "Pothole / road damage" }),
  ).toBeChecked();
  await page.getByLabel(/^Road name/).fill("MG Road");
  await page.getByLabel(/^Size/).selectOption("large");
  await page.getByLabel(/^Describe the problem/).fill(description);
}

test("a citizen reports a pothole and follows it (AC-01)", async ({ page }) => {
  const description = `Deep pothole by the bus stop (e2e ${Date.now()})`;

  // The guard sends a signed-out visitor to sign in and back again.
  await page.goto("/report");
  await expect(page).toHaveURL(/\/login\?next=%2Freport/);
  await signInThroughUi(page, SEEDED.citizen);
  await expect(page).toHaveURL(/\/report/);

  // A stale draft from an earlier run in this browser can't exist (fresh
  // context), so the flow starts at the photo step.
  await addPhoto(page);
  await continueButton(page).click();

  await locateWithGps(page);
  const { address, ward } = locationFacts(page);
  await expect(ward).toContainText(INSIDE_WARD, { timeout: 15_000 });
  // The address comes from the geocoder, which may be switched off
  // (GEOCODER=none in CI) or slow; the ward never depends on it. Either
  // way the lookup must finish, not fail.
  await expect(address).not.toBeEmpty();
  await expect(address).not.toHaveText(/couldn't check this spot/);
  await expect(address).not.toContainText("Looking up the address");
  await continueButton(page).click();

  await choosePothole(page, description);
  await continueButton(page).click();

  await expect(
    page.getByRole("heading", { name: "Check and send" }),
  ).toBeVisible();
  await expect(page.getByText(description)).toBeVisible();
  await page.getByRole("button", { name: "Send report" }).click();

  await expect(
    page.getByRole("heading", { name: "Report sent. Thank you!" }),
  ).toBeVisible();
  const referencePattern = new RegExp(`^R-${referenceYear()}-\\d{6}$`);
  const referenceText = page.getByText(referencePattern);
  await expect(referenceText).toBeVisible();
  const reference = (await referenceText.textContent())?.trim() ?? "";
  await expect(page.getByText(new RegExp(INSIDE_WARD))).toBeVisible();

  // It's in My reports...
  await page.goto("/reports");
  const card = page.getByRole("link").filter({ hasText: reference });
  await expect(card).toBeVisible();
  // Matching may still be running when the list loads (Phase 2).
  await expect(card).toContainText(/Reported|Checking for similar reports/);
  await card.click();

  // ...and its page shows the photo once the worker has processed it,
  // the details as entered, and where it stands.
  await expect(page).toHaveURL(/\/reports\/[0-9a-f-]{36}/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Pothole / road damage" }),
  ).toBeVisible();
  // Next keeps the previous page mounted but hidden (<Activity>), so the
  // list card with the same reference is still in the DOM.
  await expect(
    page.getByText(reference, { exact: true }).filter({ visible: true }),
  ).toBeVisible();
  const photo = page
    .getByRole("list", { name: `Photos of report ${reference}` })
    .locator("img");
  await expect(photo).toBeVisible({ timeout: 30_000 });
  await expect
    .poll(() => photo.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0);
  await expect(page.getByText(description)).toBeVisible();
  await expect(page.getByText("MG Road")).toBeVisible();

  // Matching runs in the background (Phase 2). The same photo at the same
  // spot on a rerun links to the earlier issue instead of opening a new one.
  await expect(
    page.getByText(
      /(New issue|Added to an existing issue|Tracked as issue) CP-\d{2}-\d{6}/,
    ),
  ).toBeVisible({ timeout: 60_000 });
  const timeline = page.getByRole("list").filter({
    has: page.getByRole("listitem").locator("time"),
  });
  await expect(timeline.getByRole("listitem").first()).toBeVisible();
  await expect(
    timeline.getByText("Reported", { exact: true }).first(),
  ).toBeVisible();
});

test("sending the same report again after a lost response creates one report", async ({
  page,
  context,
  api,
}) => {
  const session = await api.login(freshCitizenPhone());
  await giveSession(context, session);
  const description = `Overflowing bins (retry e2e ${Date.now()})`;

  await page.goto("/report");
  await addPhoto(page);
  await continueButton(page).click();
  await locateWithGps(page);
  await expect(locationFacts(page).ward).toContainText(INSIDE_WARD, {
    timeout: 15_000,
  });
  await continueButton(page).click();
  await choosePothole(page, description);
  await continueButton(page).click();

  // The first attempt reaches the API and is stored, but the phone never
  // hears back: the connection drops on the way down.
  let attempts = 0;
  const keys: string[] = [];
  await page.route("**/api/v1/reports", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    attempts += 1;
    keys.push(route.request().headers()["idempotency-key"] ?? "");
    if (attempts === 1) {
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      return route.abort("connectionreset");
    }
    return route.fallback();
  });

  await page.getByRole("button", { name: "Send report" }).click();
  await expect(page.getByText("Your report wasn't sent")).toBeVisible();
  await expect(page.getByText(/won't create a duplicate/)).toBeVisible();

  await page.getByRole("button", { name: "Try again" }).click();
  await expect(
    page.getByRole("heading", { name: "Report sent. Thank you!" }),
  ).toBeVisible();

  expect(attempts).toBe(2);
  expect(keys[0]).toBeTruthy();
  expect(keys[1]).toBe(keys[0]);
  const mine = await api.myReports(session);
  expect(mine.total).toBe(1);
  await expect(page.getByText(mine.items[0]?.reference ?? "-")).toBeVisible();
});

test.describe("outside the city", () => {
  test.use({ geolocation: { ...OUTSIDE, accuracy: 10 } });

  test("the flow won't continue from a location the city doesn't cover", async ({
    page,
    context,
    api,
  }) => {
    await giveSession(context, await api.login(freshCitizenPhone()));

    await page.goto("/report");
    await addPhoto(page);
    await continueButton(page).click();
    await locateWithGps(page);

    const warning = page
      .getByRole("alert")
      .filter({ hasText: "Outside the city" });
    await expect(warning).toBeVisible({ timeout: 15_000 });
    await expect(warning).toContainText("Move the pin inside the city");
    await expect(locationFacts(page).ward).toHaveText("—");

    await continueButton(page).click();
    await expect(
      page.getByRole("heading", { name: "Where is the problem?" }),
    ).toBeVisible();
    await expect(page).toHaveURL(/step=2/);
    await expect(warning).toBeVisible();
  });
});
