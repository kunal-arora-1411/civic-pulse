import { expectAccessible } from "../support/a11y";
import { SEEDED } from "../support/env";
import { expect, giveSession, test } from "../support/fixtures";

/*
 * Automated accessibility checks on the key flows (P6-04, WCAG 2.2 AA).
 * axe finds roughly a third of WCAG problems; the keyboard and
 * screen-reader passes are still done by hand. Serious and critical
 * violations fail the run; moderate and minor ones are attached to the
 * report so they can be worked through.
 */

const PUBLIC_PAGES = [
  ["home", "/"],
  ["login", "/login"],
  ["track", "/track"],
  ["scorecard", "/track/scorecard"],
  ["home-hindi", "/hi"],
] as const;

for (const [name, path] of PUBLIC_PAGES) {
  test(`${name} has no serious accessibility violations`, async ({ page }) => {
    await page.goto(path);
    await expect(page.locator("main").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectAccessible(page, name);
  });
}

test("the citizen's report flow and report list are accessible", async ({
  page,
  context,
  api,
}) => {
  await giveSession(context, await api.login(SEEDED.citizen));
  await page.goto("/report");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expectAccessible(page, "report-step-1");

  await page.goto("/reports");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expectAccessible(page, "my-reports");
});

test("the operator's console is accessible", async ({ page, context, api }) => {
  await giveSession(context, await api.login(SEEDED.operator));
  await page.goto("/admin/issues");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expectAccessible(page, "admin-issues");
});

test("the moderation queue is accessible", async ({ page, context, api }) => {
  await giveSession(context, await api.login(SEEDED.operator));
  await page.goto("/admin/moderation");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expectAccessible(page, "admin-moderation");
});

test("the teams and closure rules pages are accessible", async ({
  page,
  context,
  api,
}) => {
  await giveSession(context, await api.login(SEEDED.municipalAdmin));
  for (const [name, path] of [
    ["admin-teams", "/admin/teams"],
    ["admin-closure", "/admin/settings/closure"],
  ] as const) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectAccessible(page, name);
  }
});
