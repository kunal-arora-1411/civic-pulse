import { readFile } from "node:fs/promises";
import { freshCitizenPhone } from "../support/api";
import { expect, giveSession, test } from "../support/fixtures";

/*
 * Hindi smoke test: switching the language reloads the report flow in
 * Hindi. Expected strings come from the app's own message catalogue, so
 * copy edits don't break the test while a missing translation does.
 */

type Messages = {
  language: { label: string };
  report: { title: string; photos: { title: string; choose: string } };
};

async function messages(locale: "en" | "hi"): Promise<Messages> {
  const file = new URL(
    `../../apps/web/messages/${locale}.json`,
    import.meta.url,
  );
  return JSON.parse(await readFile(file, "utf8")) as Messages;
}

test("switching to Hindi shows the first report step in Hindi", async ({
  page,
  context,
  api,
}) => {
  const [en, hi] = await Promise.all([messages("en"), messages("hi")]);
  // A fresh account: switching while signed in also saves the language to
  // the profile, which must not leak into other tests' sign-ins.
  await giveSession(context, await api.login(freshCitizenPhone()));

  await page.goto("/report");
  await expect(
    page.getByRole("heading", { name: en.report.photos.title }),
  ).toBeVisible();

  await page
    .getByRole("group", { name: en.language.label })
    // The radio itself is visually hidden; people click its label.
    .getByText("हिन्दी", { exact: true })
    .click();

  await expect(page.locator("html")).toHaveAttribute("lang", "hi");
  await expect(
    page.getByRole("heading", { level: 1, name: hi.report.title }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: hi.report.photos.title }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: hi.report.photos.choose }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/report/);
  await expect(page).not.toHaveURL(/\/hi\//);
  expect(hi.report.photos.title).not.toBe(en.report.photos.title);
});
