import { freshCitizenPhone } from "../support/api";
import { freshSpot } from "../support/env";
import { expect, giveSession, test } from "../support/fixtures";

/*
 * AC-13: a citizen can't reach staff screens or staff data. The UI explains
 * itself, and the API refuses on its own, whatever the UI does.
 */

test("a citizen gets the not-authorised page and the API refuses issue access (AC-13)", async ({
  page,
  context,
  api,
}) => {
  const citizen = await api.login(freshCitizenPhone());
  // A report of their own, so there's a real issue id to ask about.
  const report = await api.createReport(citizen, {
    categoryCode: "streetlight",
    // Somewhere no other report is, so matching opens a new issue for it.
    ...freshSpot(),
    description: "Three streetlights out along the park road.",
  });
  await giveSession(context, citizen);

  for (const path of ["/admin/issues", `/admin/issues/${report.issue.id}`]) {
    await page.goto(path);
    await expect(
      page.getByRole("heading", { name: "You don't have access to this page" }),
    ).toBeVisible();
    await expect(page.getByRole("table")).toHaveCount(0);
    await expect(page.getByText(report.issue.reference)).toHaveCount(0);
  }
  await page.getByRole("link", { name: "Go to my home page" }).click();
  await expect(page).toHaveURL(/\/$/);

  const refusals = [
    await api.raw(citizen, "GET", "/issues"),
    await api.raw(
      citizen,
      "GET",
      "/issues/geojson?bbox=77.55,12.93,77.63,13.01",
    ),
    await api.raw(citizen, "GET", `/issues/${report.issue.id}`),
    await api.raw(citizen, "PATCH", `/issues/${report.issue.id}/status`, {
      to_status: "under_review",
      version: 1,
    }),
  ];
  for (const response of refusals) {
    expect([403, 404], response.url()).toContain(response.status());
    const body = (await response.json()) as { error?: { code?: string } };
    expect(["forbidden", "not_found"]).toContain(body.error?.code);
  }

  // The refused status change really didn't happen.
  const own = await api.getReport(citizen, report.id);
  expect(own.issue.status).toBe("reported");
});
