import type { Page } from "@playwright/test";
import { freshCitizenPhone } from "../support/api";
import { INSIDE, SEEDED } from "../support/env";
import { expect, giveSession, test } from "../support/fixtures";
import { signInThroughUi } from "../support/ui";

/*
 * An operator triages a citizen's report in the admin console, and the
 * citizen sees the outcome without seeing what was said internally.
 */

async function changeStatus(
  page: Page,
  to: string,
  fields: { reason?: string; note?: string } = {},
) {
  await page.getByRole("button", { name: "Change status" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByText(to, { exact: true }).click();
  if (fields.reason) await dialog.getByLabel(/^Reason/).fill(fields.reason);
  if (fields.note) {
    await dialog
      .getByLabel("Note for the citizen (optional)")
      .fill(fields.note);
  }
  return dialog;
}

test("an operator reviews and rejects a report; the citizen sees only the public part", async ({
  page,
  browser,
  api,
  photo,
}) => {
  // Arrange: a citizen has just reported a blocked drain, with a photo.
  const citizen = await api.login(freshCitizenPhone());
  const description = `Drain cover missing outside the school (e2e ${Date.now()})`;
  const report = await api.createReport(citizen, {
    categoryCode: "drainage",
    lat: INSIDE.latitude,
    lng: INSIDE.longitude,
    description,
    photo,
  });
  const issueRef = report.issue.reference;
  const reason = `Duplicate of an older complaint (internal ${Date.now()})`;
  const note = "The municipality is already handling this at the same spot.";

  // The operator finds it in the work queue by its reference.
  await page.goto("/admin/issues");
  await signInThroughUi(page, SEEDED.operator);
  await expect(page).toHaveURL(/\/admin\/issues/);
  await expect(page.getByRole("heading", { name: "Work queue" })).toBeVisible();
  await page.getByRole("searchbox", { name: "Search" }).fill(issueRef);
  await expect(page).toHaveURL(new RegExp(`q=${issueRef}`));
  const table = page.getByRole("region", { name: "Issues" });
  await expect(table.getByRole("link")).toHaveCount(1);
  await table.getByRole("link", { name: issueRef }).click();

  // The detail page has the photo and the citizen's report.
  await expect(
    page.getByRole("heading", { level: 1, name: issueRef }),
  ).toBeVisible();
  const photos = page.getByRole("list", { name: `Photos for ${issueRef}` });
  await expect(photos.locator("img")).toBeVisible({ timeout: 30_000 });
  await expect
    .poll(() =>
      photos
        .locator("img")
        .evaluate((img: HTMLImageElement) => img.naturalWidth),
    )
    .toBeGreaterThan(0);
  await expect(page.getByText(report.reference, { exact: true })).toBeVisible();
  await expect(page.getByText(description)).toBeVisible();
  await expect(page.getByText("Location from GPS")).toBeVisible();

  // reported → under review
  let dialog = await changeStatus(page, "Under review");
  await dialog.getByRole("button", { name: "Change status" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText(`${issueRef} is now Under review`)).toBeVisible();

  // under review → rejected, which needs a reason: the form says so
  // before anything is sent.
  dialog = await changeStatus(page, "Rejected", { note });
  await expect(dialog.getByText("Reason required")).toBeVisible();
  let patches = 0;
  page.on("request", (request) => {
    if (request.method() === "PATCH") patches += 1;
  });
  await dialog.getByRole("button", { name: "Change status" }).click();
  await expect(dialog.getByText("This change needs a reason.")).toBeVisible();
  await expect(dialog.getByLabel(/^Reason/)).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  expect(patches).toBe(0);

  await dialog.getByLabel(/^Reason/).fill(reason);
  await dialog.getByRole("button", { name: "Change status" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText(`${issueRef} is now Rejected`)).toBeVisible();

  // Staff history shows the reason, marked as staff-only.
  await expect(page.getByText(reason)).toBeVisible();

  // The citizen's own page shows the decision and the public note, but
  // never the internal reason.
  const citizenContext = await browser.newContext();
  try {
    await giveSession(citizenContext, citizen);
    const citizenPage = await citizenContext.newPage();
    await citizenPage.goto(`/reports/${report.id}`);
    await expect(
      citizenPage.getByText(report.reference, { exact: true }),
    ).toBeVisible();
    await expect(
      citizenPage.getByText("Status changed to Rejected"),
    ).toBeVisible();
    await expect(
      citizenPage.getByText("Status changed to Under review"),
    ).toBeVisible();
    await expect(citizenPage.getByText(note)).toBeVisible();
    await expect(citizenPage.getByText(reason)).toHaveCount(0);
    await expect(citizenPage.locator("body")).not.toContainText("Duplicate of");
  } finally {
    await citizenContext.close();
  }

  // Nor does the API hand the reason to the citizen in any field.
  const ownerView = await api.getReport(citizen, report.id);
  expect(ownerView.issue.status).toBe("rejected");
  expect(JSON.stringify(ownerView)).not.toContain(reason);
});
