import { freshCitizenPhone } from "../support/api";
import { expect, test } from "../support/fixtures";

/*
 * The OTP form against the API's real attempt limit: wrong codes count
 * down, and once the limit is used up the form asks for a new code
 * instead of a generic error.
 */

test("wrong codes count down and then lock the code", async ({ page }) => {
  await page.goto("/login");
  await page
    .getByRole("textbox", { name: "Mobile number" })
    .fill(freshCitizenPhone().replace(/^\+91/, ""));
  await page.getByRole("button", { name: "Send code" }).click();

  const code = page.getByRole("textbox", { name: "6-digit code" });
  for (const left of [4, 3, 2, 1]) {
    await code.fill("123456");
    await expect(page.getByText(`${left} attempt`)).toBeVisible();
    await expect(code).toHaveValue("");
  }

  await code.fill("123456");
  await expect(page.getByText("Too many wrong codes")).toBeVisible();
  await expect(code).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Verify and sign in" }),
  ).toBeDisabled();
  await expect(page.getByText(/Something went wrong/)).toHaveCount(0);
});
