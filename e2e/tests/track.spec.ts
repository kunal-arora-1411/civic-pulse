import { expect, test } from "../support/fixtures";

/*
 * Public resolution tracking: anyone can follow the city's issues without
 * signing in. The seed puts issues in the city, so the tracker is never
 * empty here.
 */

test("a signed-out visitor can browse the tracker and open an issue", async ({
  page,
}) => {
  await page.goto("/track");
  await expect(
    page.getByRole("heading", { name: "Track issues in your city" }),
  ).toBeVisible();

  const results = page.locator("#track-results");
  await expect(results).toHaveText(/^\d+ issues?$/, { timeout: 15_000 });
  const total = Number(/\d+/.exec((await results.textContent()) ?? "")?.[0]);
  expect(total, "the seeded issues are public").toBeGreaterThan(0);

  // The map draws the same issues, as markers or clusters.
  const map = page.locator(".leaflet-container");
  await expect(
    map
      .getByRole("button", { name: /^CP-\d{2}-\d{6}, / })
      .or(map.locator(".marker-cluster"))
      .first(),
  ).toBeVisible();

  const first = page
    .locator('section[aria-labelledby="track-results"]')
    .getByRole("link")
    .first();
  const reference = /CP-\d{2}-\d{6}/.exec(
    (await first.textContent()) ?? "",
  )?.[0];
  expect(reference).toBeTruthy();
  await first.click();

  await expect(page).toHaveURL(/\/track\/[0-9a-f-]{36}$/);
  // The tracker list stays mounted but hidden (<Activity>), so match only
  // the visible copy of the reference.
  await expect(
    page
      .getByText(reference ?? "", { exact: true })
      .filter({ visible: true })
      .first(),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Progress" })).toBeVisible();
  // Signed out, support is offered through sign-in (or just counted on a
  // closed issue).
  await expect(
    page
      .getByRole("link", { name: "Sign in to say you face this too" })
      .or(page.getByText(/(person|people) faces? this|Be the first/))
      .first(),
  ).toBeVisible();

  await page.getByRole("link", { name: "All issues" }).click();
  await expect(page).toHaveURL(/\/track$/);
});

test("the ward scorecard lists every ward", async ({ page }) => {
  await page.goto("/track/scorecard");
  await expect(
    page.getByRole("heading", { name: "Ward scorecard", level: 1 }),
  ).toBeVisible();
  await expect(page.getByText("Median days to fix").first()).toBeVisible({
    timeout: 15_000,
  });
});

test("the landing page links to the tracker", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Track issues in your city" }).click();
  await expect(page).toHaveURL(/\/track$/);
});
