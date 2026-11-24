import { expect, type Page } from "@playwright/test";
import { DEV_OTP } from "./env";

/**
 * Sign in through the login form, which the page must already show (for
 * example after a guard redirected there). The OTP field submits itself
 * once the sixth digit arrives, so there's no "Verify" click.
 */
export async function signInThroughUi(page: Page, phone: string) {
  await expect(
    page.getByRole("heading", { name: "Sign in to CivicPulse" }),
  ).toBeVisible();
  await page
    .getByRole("textbox", { name: "Mobile number" })
    .fill(phone.replace(/^\+91/, ""));
  const sendCode = page.getByRole("button", { name: "Send code" });
  const codeField = page.getByRole("textbox", { name: "6-digit code" });
  const cooldown = page.getByText(/Try again in (\d+) seconds?/);
  await sendCode.click();

  // The 30-second resend cooldown can still be running if this account
  // signed in moments ago (a rerun of the same test). Wait as long as the
  // page says, then ask again, like a person would.
  await expect(codeField.or(cooldown)).toBeVisible();
  if (await cooldown.isVisible()) {
    const text = (await cooldown.textContent()) ?? "";
    const seconds = Number(/(\d+)/.exec(text)?.[1] ?? 30);
    await page.waitForTimeout(seconds * 1000 + 250);
    await sendCode.click();
  }

  await codeField.fill(DEV_OTP);
  await expect(page).not.toHaveURL(/\/login/);
}

/** The year part of references, e.g. "26" in R-26-000123. */
export function referenceYear(): string {
  const year = new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    year: "2-digit",
  }).format(new Date());
  return year;
}
