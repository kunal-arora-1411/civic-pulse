import { SEEDED } from "../support/env";
import { expect, giveSession, test } from "../support/fixtures";

/*
 * Every admin screen loads real data from the API without an error state.
 * This is a cheap guard against the two sides drifting apart: the web app
 * validates each response against its schema, so a renamed field or a
 * changed envelope shows up here as "Couldn't load …".
 */

const SCREENS = [
  { path: "/admin", heading: /^Welcome back/ },
  { path: "/admin/issues", heading: "Work queue", table: "Issues" },
  { path: "/admin/categories", heading: "Categories", table: "Categories" },
  { path: "/admin/users", heading: "Users", table: "Users" },
  { path: "/admin/audit", heading: "Audit log", table: "Audit events" },
] as const;

test("each admin screen loads for a municipal admin", async ({
  page,
  context,
  api,
}) => {
  await giveSession(context, await api.login(SEEDED.municipalAdmin));

  for (const screen of SCREENS) {
    await test.step(screen.path, async () => {
      await page.goto(screen.path);
      await expect(
        page.getByRole("heading", { level: 1, name: screen.heading }),
      ).toBeVisible();
      if ("table" in screen) {
        const rows = page
          .getByRole("table", { name: screen.table })
          .or(
            page.getByRole("region", { name: screen.table }).getByRole("table"),
          )
          .getByRole("row");
        // A header row plus at least one data row from the seed.
        await expect(rows.nth(1)).toBeVisible();
      }
      await expect(page.getByText(/^Couldn't load/)).toHaveCount(0);
    });
  }

  // The seeded categories come back with their Hindi names.
  await page.goto("/admin/categories");
  await expect(page.getByText("गड्ढा / सड़क क्षति")).toBeVisible();
});
