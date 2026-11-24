import { SEEDED } from "../support/env";
import { expect, giveSession, test } from "../support/fixtures";

/*
 * The staff map (FR-045, FR-046, FR-050): the seeded issues load as
 * clustered markers, and picking a marker highlights its row in the list.
 */

test("the issue map shows the seeded issues and picking a marker selects its row", async ({
  page,
  context,
  api,
}) => {
  // The Roads supervisor has no ward scope, so sees every issue.
  await giveSession(context, await api.login(SEEDED.supervisor));
  await page.goto("/admin/map");
  await expect(page.getByRole("heading", { name: "Issue map" })).toBeVisible();

  const list = page.locator('section[aria-labelledby="map-list-heading"]');
  const count = list.getByText(/^\d+ issues?$/);
  await expect(count).toBeVisible({ timeout: 15_000 });
  const shown = Number(/\d+/.exec((await count.textContent()) ?? "")?.[0]);
  // The seed puts 60 issues in the city; other tests only ever add more.
  expect(
    shown,
    "the seeded issues should all be in view",
  ).toBeGreaterThanOrEqual(60);

  const map = page.locator(".leaflet-container");
  const markers = map.getByRole("button", { name: /^CP-\d{2}-\d{6}, / });
  const clusters = map.locator(".marker-cluster");
  await expect(markers.or(clusters).first()).toBeVisible();

  // At city zoom most issues sit in clusters. Open clusters (each click
  // zooms in, or fans the markers out at the deepest zoom) until single
  // markers show, waiting for each zoom animation to finish.
  const settled = () =>
    expect(page.locator(".leaflet-container.leaflet-zoom-anim")).toHaveCount(0);
  for (let i = 0; i < 8 && (await markers.count()) === 0; i++) {
    await clusters.first().click();
    await settled();
    await expect(
      list.getByRole("heading", { name: "In the selected cluster" }),
    ).toBeVisible();
  }
  await expect(markers.first()).toBeVisible();

  const marker = markers.first();
  const name = (await marker.getAttribute("title")) ?? "";
  const reference = name.split(",")[0] ?? "";
  expect(reference).toMatch(/^CP-\d{2}-\d{6}$/);

  await marker.click();

  const row = list.getByRole("button", { name: new RegExp(`^${reference}`) });
  await expect(row).toHaveAttribute("aria-pressed", "true");
  await expect(row).toBeInViewport();
  await expect(
    list.getByRole("button", { pressed: true }),
    "exactly one row is highlighted",
  ).toHaveCount(1);
  await expect(
    list.locator("li", {
      has: page.getByRole("button", { pressed: true }),
    }),
  ).toHaveClass(/bg-primary-soft/);

  // Picking it again clears the selection.
  await marker.click();
  await expect(row).toHaveAttribute("aria-pressed", "false");
});
