import { fileURLToPath } from "node:url";
import { expectAccessible } from "../support/a11y";
import type { Api, Session } from "../support/api";
import { freshCitizenPhone } from "../support/api";
import { INSIDE, PHOTO_PATH, SEEDED } from "../support/env";
import { expect, giveSession, PHONE, test } from "../support/fixtures";
import { signInThroughUi } from "../support/ui";

/*
 * Phase 3, the operational loop (AC-10 to AC-12): a supervisor assigns a
 * verified pothole to the seeded "Roads North" team and its field worker;
 * the worker accepts, starts, posts an update and marks it fixed with an
 * after photo in the field app; the supervisor approves on the issue
 * page; the citizen who reported it says it's still broken, which
 * reopens it.
 *
 * The supervisor signs in through the API (map.spec.ts uses that number
 * through the UI; `api.login` waits out the OTP cooldown if they race)
 * and the session is handed to a browser context, so no second OTP is
 * needed for the UI steps.
 */

type IssueDetail = {
  id: string;
  reference: string;
  status: string;
  version: number;
  allowed_transitions: { to_status: string }[];
  operations?: {
    assignment: {
      team: { name: string };
      work_order: { id: string; state: string } | null;
    } | null;
  } | null;
};

/** A point in Synthetic Ward 2 (Zone North), away from other tests' pins. */
function wardTwoPoint() {
  return {
    lat: INSIDE.latitude + 0.01 + Math.random() * 0.02,
    lng: INSIDE.longitude + 0.005 + Math.random() * 0.02,
  };
}

/** Walk the issue to `verified` through whatever transitions it offers. */
async function verify(api: Api, staff: Session, issueId: string) {
  for (let step = 0; step < 3; step++) {
    const issue = await api.send<IssueDetail>(
      staff,
      "GET",
      `/issues/${issueId}`,
    );
    if (issue.status === "verified") return issue;
    const next = issue.allowed_transitions.some(
      (t) => t.to_status === "verified",
    )
      ? "verified"
      : "under_review";
    await api.send(staff, "PATCH", `/issues/${issueId}/status`, {
      to_status: next,
      version: issue.version,
    });
  }
  throw new Error(`Couldn't verify issue ${issueId}`);
}

test.describe.configure({ mode: "serial" });

test("assign, field work, approval and a citizen reopen (AC-10 to AC-12)", async ({
  page,
  browser,
  api,
  photo,
}) => {
  test.setTimeout(240_000);

  // Arrange: a citizen reports a pothole in Zone North.
  const citizen = await api.login(freshCitizenPhone());
  const point = wardTwoPoint();
  const report = await api.createReport(citizen, {
    categoryCode: "pothole",
    ...point,
    description: `Pothole by the bus stop (e2e ops ${Date.now()})`,
    photo,
  });
  const issueId = report.issue.id;
  const issueRef = report.issue.reference;

  // AC-10: the supervisor verifies it and assigns it to Roads North.
  const supervisor = await api.login(SEEDED.supervisor);
  const verified = await verify(api, supervisor, issueId);
  const eligible = await api.send<
    {
      team: { id: string; name: string };
      members: { user: { id: string; display_name: string | null } }[];
    }[]
  >(supervisor, "GET", `/issues/${issueId}/eligible-teams`);
  const roads = eligible.find((item) => item.team.name === "Roads North");
  expect(
    roads,
    "Roads North is eligible for a Zone North pothole",
  ).toBeTruthy();
  const worker = roads?.members[0]?.user;
  expect(worker).toBeTruthy();
  const assigned = await api.send<IssueDetail>(
    supervisor,
    "POST",
    `/issues/${issueId}/assignments`,
    {
      team_id: roads?.team.id,
      assignee_id: worker?.id,
      note: "Please fix before the monsoon",
      version: verified.version,
    },
  );
  expect(assigned.status).toBe("assigned");
  expect(assigned.operations?.assignment?.work_order?.state).toBe(
    "pending_acceptance",
  );
  const workOrderId = assigned.operations?.assignment?.work_order?.id;

  // The field worker, on a phone, finds the job in their queue.
  const field = await browser.newContext({ ...PHONE });
  const fieldPage = await field.newPage();
  await fieldPage.goto("/field");
  await signInThroughUi(fieldPage, SEEDED.fieldWorker);
  await expect(fieldPage).toHaveURL(/\/field/);
  const queue = fieldPage.getByRole("list", { name: "Active" });
  await expect(queue).toBeVisible();
  await expectAccessible(fieldPage, "field-queue");
  await queue.getByText(issueRef).click();
  await expect(fieldPage).toHaveURL(
    new RegExp(`/field/work-orders/${workOrderId}`),
  );
  // No reporter details reach the field app.
  await expect(fieldPage.getByText(citizen.phone)).toHaveCount(0);
  await expect(
    fieldPage.getByRole("link", { name: /get directions/i }),
  ).toHaveAttribute("href", /google\.com\/maps\/dir/);

  await expectAccessible(fieldPage, "field-work-order");

  // Accept, start, post an update.
  await fieldPage.getByRole("button", { name: "Accept job" }).click();
  await fieldPage.getByRole("button", { name: "Start work" }).click();
  await expect(
    fieldPage.getByRole("button", { name: "Mark as fixed" }),
  ).toBeVisible();
  await fieldPage.getByRole("button", { name: "Add update" }).click();
  let dialog = fieldPage.getByRole("dialog");
  await dialog.getByLabel(/^Note/).fill("Cutting the edges, cold mix next");
  await dialog.getByRole("button", { name: "Post update" }).click();
  await expect(
    fieldPage.getByText("Cutting the edges, cold mix next"),
  ).toBeVisible();

  // Mark it fixed with an after photo (AC-11 needs evidence).
  await fieldPage.getByRole("button", { name: "Mark as fixed" }).click();
  dialog = fieldPage.getByRole("dialog");
  await dialog
    .locator('input[type="file"][multiple]')
    .setInputFiles(fileURLToPath(PHOTO_PATH));
  await expect(dialog.getByText("Uploaded")).toBeVisible({ timeout: 60_000 });
  await dialog.getByRole("button", { name: "Send for approval" }).click();
  await expect(fieldPage.getByText("Waiting for approval")).toBeVisible();
  await field.close();

  // AC-11: the supervisor sees the pending fix and approves it.
  const staff = await browser.newContext();
  await giveSession(staff, supervisor);
  const staffPage = await staff.newPage();
  await staffPage.goto(`/admin/issues/${issueId}`);
  await expect(
    staffPage.getByRole("heading", { level: 1, name: issueRef }),
  ).toBeVisible();
  await expect(staffPage.getByText("Fix awaiting approval")).toBeVisible();
  await staffPage.getByRole("button", { name: "Approve fix" }).click();
  dialog = staffPage.getByRole("dialog");
  await dialog
    .getByLabel("Note for the citizens (optional)")
    .fill("Filled and levelled.");
  await dialog.getByRole("button", { name: "Approve fix" }).click();
  await expect(staffPage.getByText("Resolved").first()).toBeVisible();
  // The workload view counts the job against Roads North.
  await staffPage.goto("/admin/workload");
  await expect(
    staffPage.getByRole("heading", { level: 2, name: "Roads North" }),
  ).toBeVisible();
  await expectAccessible(staffPage, "admin-workload");
  await staffPage.goto("/admin/moderation");
  await expect(
    staffPage.getByRole("heading", { level: 1, name: "Moderation" }),
  ).toBeVisible();
  await expectAccessible(staffPage, "admin-moderation");
  await staff.close();

  // AC-12: the citizen says it's still broken, and the issue reopens.
  await giveSession(page.context(), citizen);
  await page.goto(`/reports/${report.id}`);
  await expect(page.getByText("Is it fixed?")).toBeVisible();
  await page.getByRole("button", { name: "No, still broken" }).click();
  await page.getByLabel("What's still wrong?").fill("Water still pools here");
  await page.getByRole("button", { name: "Send: still broken" }).click();
  await expect(
    page.getByText(/sent it back to the municipality/),
  ).toBeVisible();

  const after = await api.send<IssueDetail>(
    supervisor,
    "GET",
    `/issues/${issueId}`,
  );
  // Reopened issues go back to be assigned again.
  expect(after.status).toBe("reopened");
});

test("a field worker can't open someone else's work order", async ({
  browser,
  api,
}) => {
  const field = await browser.newContext({ ...PHONE });
  const worker = await api.login(SEEDED.fieldWorker);
  await giveSession(field, worker);
  const page = await field.newPage();
  await page.goto("/field/work-orders/00000000-0000-4000-8000-000000000000");
  await expect(page.getByText("Work order not found")).toBeVisible();
  await field.close();
});
