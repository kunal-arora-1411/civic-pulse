import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { type Api, freshCitizenPhone } from "../support/api";
import {
  eastOf,
  freshSpot,
  OTHER_POTHOLE_PHOTO,
  POTHOLE_PHOTO,
} from "../support/env";
import { expect, giveSession, PHONE, test } from "../support/fixtures";
import {
  addPhotoFile,
  continueButton,
  fillPotholeDetails,
  locateWithGps,
  sendReport,
} from "../support/report-flow";
import { realModel, staffPhone } from "../support/staff";

/*
 * Phase 2 acceptance criteria against the real vision model (CLIP on the
 * ai-worker), with real, openly licensed pothole photos (fixtures/).
 *
 * Every scenario happens at a fresh spot in the empty West Delhi area, so
 * the only candidates matching can find are the ones the test made.
 */

test.skip(
  () => !realModel(),
  "needs the real vision model; this stack runs the fake one",
);
test.describe.configure({ timeout: 120_000 });

const pothole = () => readFile(fileURLToPath(POTHOLE_PHOTO));
const otherPothole = () => readFile(fileURLToPath(OTHER_POTHOLE_PHOTO));

async function citizenReport(
  api: Api,
  spot: { lat: number; lng: number },
  photo: Buffer | undefined,
  description: string,
) {
  const session = await api.login(freshCitizenPhone());
  const report = await api.submitReport(session, {
    categoryCode: "pothole",
    ...spot,
    description,
    photo,
  });
  return { session, report };
}

/**
 * Two potholes 5 m apart, photographed differently: close enough that the
 * matcher must consider them, but the photos are of different scenes, so
 * it may not link them on its own.
 */
async function nearbyDifferentScene(api: Api, label: string) {
  const spot = freshSpot();
  const first = await citizenReport(
    api,
    spot,
    await pothole(),
    `Pothole (${label} first, e2e ${Date.now()})`,
  );
  const issue = (await api.waitForIssue(first.session, first.report.id)).issue;
  const second = await citizenReport(
    api,
    eastOf(spot, 5),
    await otherPothole(),
    `Another pothole nearby (${label} second, e2e ${Date.now()})`,
  );
  const matched = await api.waitForMatching(second.session, second.report.id);
  return { issue, second, matched };
}

test.describe("on a phone", () => {
  test.use({ ...PHONE, permissions: ["geolocation"] });

  test("a real pothole photo gets a pothole suggestion (AC-02)", async ({
    page,
    context,
    api,
  }) => {
    const session = await api.login(freshCitizenPhone());
    await giveSession(context, session);
    const spot = freshSpot();
    await context.setGeolocation({
      latitude: spot.lat,
      longitude: spot.lng,
      accuracy: 10,
    });

    await page.goto("/report");
    await addPhotoFile(page, POTHOLE_PHOTO);
    await continueButton(page).click();
    await locateWithGps(page);
    await continueButton(page).click();

    // The suggestion is asked for as soon as the photo is uploaded, so by
    // now it has usually arrived; give the model time if it hasn't.
    await expect(
      page.getByRole("heading", { name: "What kind of problem is it?" }),
    ).toBeVisible();
    await expect(page.getByText("We picked this from your photo")).toBeVisible({
      timeout: 30_000,
    });
    await expect(
      page.getByText("This looks like Pothole / road damage."),
    ).toBeVisible();
    const choice = page.getByRole("radio", { name: /Pothole \/ road damage/ });
    await expect(choice).toBeChecked();
    await expect(page.getByText("Suggested from your photo")).toBeVisible();

    await fillPotholeDetails(page, `Suggested pothole (e2e ${Date.now()})`);
    await continueButton(page).click();
    const reference = await sendReport(page);

    // The citizen kept the suggestion, and that is what was recorded.
    const mine = await api.myReports(session);
    const id = mine.items.find((item) => item.reference === reference)?.id;
    expect(id).toBeTruthy();
    const operator = await api.login(staffPhone("ac04Operator"));
    const staffView = (await api.getReport(operator, id ?? "")) as {
      category_source?: string;
    };
    expect(staffView.category_source).toBe("ai_accepted");
  });
});

test("the same photo reported twice links to one issue and the counts go up (AC-04)", async ({
  page,
  context,
  api,
}) => {
  const spot = freshSpot();
  const photo = await pothole();
  const first = await citizenReport(
    api,
    spot,
    photo,
    `Pothole (AC-04 first, e2e ${Date.now()})`,
  );
  const issue = (await api.waitForIssue(first.session, first.report.id)).issue;
  expect(issue.report_count).toBe(1);

  // A neighbour photographs... the same photo, 3 m away.
  const second = await citizenReport(
    api,
    eastOf(spot, 3),
    photo,
    `Same pothole (AC-04 second, e2e ${Date.now()})`,
  );
  const linked = await api.waitForIssue(second.session, second.report.id);
  expect(linked.matching_status).toBe("linked");
  expect(linked.issue.id).toBe(issue.id);
  expect(linked.issue.report_count).toBe(2);
  expect(linked.issue.unique_reporter_count).toBe(2);

  // Staff can see why: the same photo, linked by the system.
  const operator = await api.login(staffPhone("ac04Operator"));
  const staffView = await api.getReport(operator, second.report.id);
  const decision = staffView.match_decisions?.[0];
  expect(decision?.decision).toBe("auto_linked");
  expect(decision?.candidate_issue_id).toBe(issue.id);
  expect(decision?.signals.same_photo).toBe(true);
  expect(decision?.signals.visual).toBe(1);
  expect(decision?.score).toBeGreaterThanOrEqual(
    decision?.signals.thresholds.auto ?? 1,
  );

  // And the second citizen is told they joined an existing issue.
  await giveSession(context, second.session);
  await page.goto(`/reports/${second.report.id}`);
  await expect(
    page.getByText(`Added to an existing issue ${issue.reference}`),
  ).toBeVisible();
  await expect(
    page.getByText("2 people have reported this problem."),
  ).toBeVisible();
});

test("a different pothole a few metres away isn't linked automatically (AC-05)", async ({
  api,
}) => {
  const { issue, second, matched } = await nearbyDifferentScene(api, "AC-05");

  expect(matched.matching_status).not.toBe("linked");
  expect(matched.issue?.id ?? null).not.toBe(issue.id);

  const operator = await api.login(staffPhone("ac05Operator"));
  const staffView = await api.getReport(operator, second.report.id);
  const decision = staffView.match_decisions?.find(
    (d) => d.candidate_issue_id === issue.id,
  );
  expect(decision, "the nearby issue was considered").toBeTruthy();
  expect(decision?.decision).not.toBe("auto_linked");
  // It is close, but the photos show different scenes.
  expect(decision?.signals.distance_m).toBeLessThan(10);
  expect(decision?.signals.same_photo).toBe(false);
  expect(decision?.signals.visual).not.toBeNull();
  expect(decision?.signals.visual ?? 1).toBeLessThan(
    decision?.signals.thresholds.visual_min ?? 0,
  );
  const first = await api.getIssue(operator, issue.id);
  expect(first.report_count).toBe(1);

  // Leave nothing open in the review queue for other tests.
  if (matched.matching_status === "review") {
    const task = await api.reviewTaskFor(operator, second.report.id);
    if (task)
      await api.resolveReview(operator, task.id, { action: "new_issue" });
  }
});

test("an uncertain match waits for an operator, who links it in the review queue (AC-06)", async ({
  page,
  context,
  api,
}) => {
  const { issue, second, matched } = await nearbyDifferentScene(api, "AC-06");
  expect(matched.matching_status).toBe("review");
  expect(matched.issue).toBeNull();

  const operator = await api.login(staffPhone("ac06Operator"));
  const task = await api.reviewTaskFor(operator, second.report.id);
  expect(task, "a review task was opened").toBeTruthy();
  expect(task?.candidates[0]?.issue.id).toBe(issue.id);

  await giveSession(context, operator);
  await page.goto(`/admin/review?task=${task?.id}`);
  await expect(
    page.getByRole("heading", { name: "Review queue" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: new RegExp(second.report.reference) }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Why it was suggested" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: `Same problem: add to ${issue.reference}` })
    .click();
  await expect(
    page.getByText(`${second.report.reference} added to ${issue.reference}`),
  ).toBeVisible();

  const placed = await api.getReport(second.session, second.report.id);
  expect(placed.matching_status).toBe("linked");
  expect(placed.issue.id).toBe(issue.id);
  expect(placed.issue.report_count).toBe(2);
  expect(await api.reviewTaskFor(operator, second.report.id)).toBeUndefined();
  const staffView = await api.getReport(operator, second.report.id);
  expect(
    staffView.match_decisions?.find((d) => d.candidate_issue_id === issue.id)
      ?.decision,
  ).toBe("chosen_by_reviewer");
});

/** Opens an issue's staff page and waits for it to load. */
async function openIssue(page: Page, issue: { id: string; reference: string }) {
  await page.goto(`/admin/issues/${issue.id}`);
  await expect(
    page.getByRole("heading", { level: 1, name: issue.reference }),
  ).toBeVisible();
}

test("an operator merges two issues through the UI (AC-07)", async ({
  page,
  context,
  api,
}) => {
  // Two reports of one problem that matching kept apart (200 m apart).
  const spot = freshSpot();
  const a = await citizenReport(api, spot, undefined, `Broken road (AC-07 a)`);
  const b = await citizenReport(
    api,
    eastOf(spot, 200),
    undefined,
    `Broken road further along (AC-07 b)`,
  );
  const survivor = (await api.waitForIssue(a.session, a.report.id)).issue;
  const merged = (await api.waitForIssue(b.session, b.report.id)).issue;
  expect(merged.id).not.toBe(survivor.id);

  const operator = await api.login(staffPhone("ac07Operator"));
  await giveSession(context, operator);
  await openIssue(page, survivor);
  await page.getByRole("button", { name: "Merge into this" }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("searchbox", { name: "Issues to merge in" })
    .fill(merged.reference);
  await dialog.getByRole("checkbox", { name: merged.reference }).check();
  await dialog.getByLabel(/^Reason/).fill("The same stretch of broken road.");
  await dialog.getByRole("button", { name: "Review the merge" }).click();
  await expect(dialog.getByText("Please check before you merge")).toBeVisible();
  await dialog.getByRole("button", { name: "Merge 1 issue" }).click();
  await expect(
    page.getByText(`Merged 1 issue into ${survivor.reference}`),
  ).toBeVisible();

  const after = await api.getIssue(operator, survivor.id);
  expect(after.report_count).toBe(2);
  expect(after.unique_reporter_count).toBe(2);
  const gone = await api.getIssue(operator, merged.id);
  expect(gone.merged_into?.id).toBe(survivor.id);
  // The citizen whose report moved now follows the survivor.
  const moved = await api.getReport(b.session, b.report.id);
  expect(moved.issue.id).toBe(survivor.id);

  // Opening the merged issue lands on the survivor.
  await page.goto(`/admin/issues/${merged.id}`);
  await expect(
    page.getByRole("heading", { level: 1, name: survivor.reference }),
  ).toBeVisible();
});

test("an operator splits a wrongly linked report out through the UI (AC-08)", async ({
  page,
  context,
  api,
}) => {
  // Two reports linked automatically (the same photo at the same spot).
  const spot = freshSpot();
  const photo = await pothole();
  const a = await citizenReport(api, spot, photo, "Pothole (AC-08 a)");
  const issue = (await api.waitForIssue(a.session, a.report.id)).issue;
  const b = await citizenReport(
    api,
    eastOf(spot, 2),
    photo,
    "Pothole, or so it seemed (AC-08 b)",
  );
  const linked = await api.waitForIssue(b.session, b.report.id);
  expect(linked.issue.id).toBe(issue.id);

  const operator = await api.login(staffPhone("ac08Operator"));
  await giveSession(context, operator);
  await openIssue(page, issue);
  await page.getByRole("button", { name: "Split" }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("checkbox", { name: new RegExp(b.report.reference) })
    .check();
  await expect(
    dialog.getByRole("radio", { name: "A new issue" }),
  ).toBeChecked();
  await dialog
    .getByLabel(/^Reason/)
    .fill("The second photo is of a different spot.");
  await dialog.getByRole("button", { name: "Move 1 report" }).click();
  await expect(
    page.getByText(/^Moved 1 report to CP-\d{2}-\d{6}$/),
  ).toBeVisible();

  const source = await api.getIssue(operator, issue.id);
  expect(source.report_count).toBe(1);
  expect(source.reports.map((r) => r.id)).toEqual([a.report.id]);
  const moved = await api.getReport(b.session, b.report.id);
  expect(moved.issue.id).not.toBe(issue.id);
  expect(moved.issue.report_count).toBe(1);
});
