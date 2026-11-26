import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import type { Session } from "../support/api";
import { SEEDED, WEB_URL } from "../support/env";
import { giveSession, test } from "../support/fixtures";

/*
 * Regenerate the screenshots the README shows.
 *
 *   pnpm --filter @civicpulse/e2e exec playwright install chromium   # once
 *   CAPTURE=1 pnpm --filter @civicpulse/e2e exec playwright test tests/screenshots.spec.ts
 *
 * It needs the same seeded stack the e2e suite needs, and writes to
 * docs/screenshots. Skipped unless CAPTURE is set: a normal test run has no
 * business writing images, and CI has neither the fonts nor the map tiles
 * to draw them the same way. Regenerate after a change that alters what a
 * screen looks like, and commit the PNGs with it.
 */

const OUT = fileURLToPath(new URL("../../docs/screenshots/", import.meta.url));
const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };

type Size = { width: number; height: number };

test.describe("README screenshots", () => {
  test.skip(
    !process.env.CAPTURE,
    "Set CAPTURE=1 to regenerate docs/screenshots",
  );

  test("captures the screens the README shows", async ({ browser, api }) => {
    await mkdir(OUT, { recursive: true });

    const shoot = async (
      name: string,
      url: string,
      size: Size,
      session?: Session,
      ready?: (page: Page) => Promise<void>,
    ) => {
      const context = await browser.newContext({
        viewport: size,
        deviceScaleFactor: 2,
        locale: "en-IN",
        timezoneId: "Asia/Kolkata",
      });
      if (session) await giveSession(context, session);
      const page = await context.newPage();
      await page.goto(`${WEB_URL}${url}`, { waitUntil: "domcontentloaded" });
      // Screens that fetch render a skeleton first; waiting for the real
      // content is the difference between a screenshot of the product and
      // a screenshot of a loading state.
      if (ready) await ready(page);
      else await page.waitForLoadState("networkidle").catch(() => {});
      await page.waitForTimeout(600);
      await page.screenshot({ path: `${OUT}${name}.png` });
      await context.close();
      return page;
    };

    const tiles = async (page: Page) =>
      page
        .locator(".leaflet-tile-loaded")
        .first()
        .waitFor({ timeout: 15_000 })
        .catch(() => {});

    const admin = await api.login(SEEDED.municipalAdmin);
    const citizen = await api.login(SEEDED.citizen);

    // Signed out: the pitch, and the tracker anyone can follow.
    await shoot("landing", "/", DESKTOP);
    await shoot("public-track", "/track", DESKTOP, undefined, async (page) => {
      await page.getByRole("heading").first().waitFor();
      await tiles(page);
    });

    // The citizen's side, on a phone, because that's where reports come from.
    await shoot("citizen-report", "/report", MOBILE, citizen, async (page) => {
      await page.getByRole("heading").first().waitFor();
    });
    await shoot(
      "citizen-reports",
      "/reports",
      MOBILE,
      citizen,
      async (page) => {
        await page.getByRole("heading").first().waitFor();
        await page.locator("main a[href*='/reports/']").first().waitFor();
      },
    );

    // The staff console.
    await shoot(
      "admin-issues",
      "/admin/issues",
      DESKTOP,
      admin,
      async (page) => {
        await page.getByRole("heading").first().waitFor();
        await page.locator("table tbody tr").first().waitFor();
      },
    );
    await shoot(
      "admin-analytics",
      "/admin/analytics",
      DESKTOP,
      admin,
      async (page) => {
        await page
          .getByRole("list", { name: "Headline figures" })
          .waitFor({ timeout: 30_000 });
        await page.waitForTimeout(1500); // let the charts finish drawing
      },
    );
    await shoot(
      "admin-review",
      "/admin/review",
      DESKTOP,
      admin,
      async (page) => {
        await page.getByRole("heading").first().waitFor();
      },
    );
    await shoot("admin-map", "/admin/map", DESKTOP, admin, async (page) => {
      await page.getByRole("heading").first().waitFor();
      await tiles(page);
    });

    // One issue, in the detail view staff actually work in.
    const context = await browser.newContext({
      viewport: DESKTOP,
      deviceScaleFactor: 2,
      locale: "en-IN",
      timezoneId: "Asia/Kolkata",
    });
    await giveSession(context, admin);
    const page = await context.newPage();
    await page.goto(`${WEB_URL}/admin/issues`, {
      waitUntil: "domcontentloaded",
    });
    await page.locator("table tbody tr a").first().waitFor();
    const href = await page
      .locator("table tbody tr a")
      .first()
      .getAttribute("href");
    if (href) {
      await page.goto(`${WEB_URL}${href}`, { waitUntil: "domcontentloaded" });
      await page.getByRole("heading").first().waitFor();
      await page.waitForTimeout(800);
      await page.screenshot({ path: `${OUT}issue-detail.png` });
    }
    await context.close();
  });
});
