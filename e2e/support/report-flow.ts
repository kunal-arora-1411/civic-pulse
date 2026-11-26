import { fileURLToPath } from "node:url";
import { expect, type Page } from "@playwright/test";

/*
 * Steps of the citizen report flow, for the tests that walk through it
 * with a particular photo or place (report.spec.ts has its own copies,
 * with the comments on why each wait is there).
 */

export const continueButton = (page: Page) =>
  page.getByRole("button", { name: "Continue" });

export async function addPhotoFile(page: Page, photo: URL) {
  await expect(
    page.getByRole("heading", { name: "Add photos of the problem" }),
  ).toBeVisible();
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Choose from gallery" }).click();
  await (await chooser).setFiles(fileURLToPath(photo));
  await expect(page.getByText("1 of 1 uploaded")).toBeVisible({
    timeout: 30_000,
  });
}

/** Uses the browser's (test-set) position and waits for its ward. */
export async function locateWithGps(page: Page) {
  await expect(
    page.getByRole("heading", { name: "Where is the problem?" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Use my location" }).click();
  await expect(page.getByText(/Location found, accurate to/)).toBeVisible();
  const facts = page.locator("dl").filter({ hasText: "Address" });
  await expect(facts.locator("dt:text-is('Ward') + dd")).toContainText(
    "Synthetic Ward",
    { timeout: 15_000 },
  );
  await expect(facts.locator("dt:text-is('Address') + dd")).not.toContainText(
    "Looking up the address",
  );
}

export async function fillPotholeDetails(page: Page, description: string) {
  await page.getByLabel(/^Road name/).fill("Test Road");
  await page.getByLabel(/^Size/).selectOption("large");
  await page.getByLabel(/^Describe the problem/).fill(description);
}

export async function sendReport(page: Page): Promise<string> {
  await expect(
    page.getByRole("heading", { name: "Check and send" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Send report" }).click();
  await expect(
    page.getByRole("heading", { name: "Report sent. Thank you!" }),
  ).toBeVisible();
  const reference = page.getByText(/^R-\d{2}-\d{6}$/);
  await expect(reference).toBeVisible();
  return ((await reference.textContent()) ?? "").trim();
}
