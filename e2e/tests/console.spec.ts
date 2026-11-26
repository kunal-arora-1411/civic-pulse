import { expectAccessible } from "../support/a11y";
import { expect, giveSession, test } from "../support/fixtures";
import { staffPhone } from "../support/staff";

/*
 * Every admin screen loads real data from the API without an error state.
 * This is a cheap guard against the two sides drifting apart: the web app
 * validates each response against its schema, so a renamed field or a
 * changed envelope shows up here as "Couldn't load …".
 */

const SCREENS = [
  { nav: "Work queue", heading: "Work queue", table: "Issues" },
  { nav: "Categories", heading: "Categories", table: "Categories" },
  { nav: "Teams", heading: "Teams", table: "Teams" },
  { nav: "Users", heading: "Users", table: "Users" },
  { nav: "Audit log", heading: "Audit log", table: "Audit events" },
] as const;

test("each admin screen loads for a municipal admin", async ({
  page,
  context,
  api,
}) => {
  await giveSession(context, await api.login(staffPhone("consoleAdmin")));
  await page.goto("/admin");
  await expect(
    page.getByRole("heading", { level: 1, name: /^Welcome back/ }),
  ).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Admin sections" });

  for (const screen of SCREENS) {
    await test.step(screen.nav, async () => {
      await nav.getByRole("link", { name: screen.nav }).click();
      await expect(
        page.getByRole("heading", { level: 1, name: screen.heading }),
      ).toBeVisible();
      // Earlier screens stay mounted but hidden (<Activity>), hence the
      // visibility filters.
      const table = page
        .getByRole("table", { name: screen.table })
        .or(page.getByRole("region", { name: screen.table }).getByRole("table"))
        .filter({ visible: true });
      // A header row plus at least one data row from the seed.
      await expect(table.getByRole("row").nth(1)).toBeVisible();
      await expect(
        page.getByText(/^Couldn't load/).filter({ visible: true }),
      ).toHaveCount(0);
    });
  }

  // The Phase 3 configuration pages pass the automated accessibility
  // checks (a11y.spec.ts covers the rest; this account signs in here only).
  await nav.getByRole("link", { name: "Teams" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Teams" }),
  ).toBeVisible();
  await expectAccessible(page, "admin-teams");
  await nav.getByRole("link", { name: "Closure rules" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Closure rules" }),
  ).toBeVisible();
  await expectAccessible(page, "admin-closure");

  // The seeded categories come back with their Hindi names.
  await nav.getByRole("link", { name: "Categories" }).click();
  await expect(
    page.getByText("गड्ढा / सड़क क्षति").filter({ visible: true }),
  ).toBeVisible();
});
