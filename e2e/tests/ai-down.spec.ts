import { execSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { freshCitizenPhone } from "../support/api";
import { COMPOSE, eastOf, freshSpot, POTHOLE_PHOTO } from "../support/env";
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
 * AC-03: with the AI worker stopped, a citizen can still report. The
 * category is chosen by hand, and matching falls back to location,
 * category and time after two minutes, which can send a report to review
 * but never links it automatically, even when the photo is the same.
 *
 * This stops the stack's ai-worker (E2E_COMPOSE says how to reach the
 * stack), so it runs in its own Playwright project, after every other
 * test, and starts the worker again whatever happens.
 */

const REPO_ROOT = fileURLToPath(new URL("../..", import.meta.url));

function compose(args: string) {
  return execSync(`${COMPOSE} ${args}`, {
    cwd: REPO_ROOT,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
}

async function waitForHealthyWorker() {
  const deadline = Date.now() + 180_000;
  for (;;) {
    const health = compose("ps ai-worker --format {{.Health}}").trim();
    if (health === "healthy") return;
    if (Date.now() > deadline) {
      throw new Error(`The ai-worker didn't become healthy (${health})`);
    }
    await new Promise((resolve) => setTimeout(resolve, 3_000));
  }
}

test.skip(
  () => !realModel(),
  "needs the real vision model; this stack runs the fake one",
);
test.use({ ...PHONE, permissions: ["geolocation"] });

test("with the AI worker stopped, a report is still accepted and matched without it (AC-03)", async ({
  page,
  context,
  api,
}) => {
  test.setTimeout(480_000);

  // An existing issue, with the photo the citizen is about to send.
  const spot = freshSpot();
  const neighbour = await api.login(freshCitizenPhone());
  const existing = await api.createReport(neighbour, {
    categoryCode: "pothole",
    ...spot,
    description: `Pothole (AC-03 existing, e2e ${Date.now()})`,
    photo: await readFile(fileURLToPath(POTHOLE_PHOTO)),
  });

  compose("stop ai-worker");
  try {
    const citizen = await api.login(freshCitizenPhone());
    await giveSession(context, citizen);
    const here = eastOf(spot, 4);
    await context.setGeolocation({
      latitude: here.lat,
      longitude: here.lng,
      accuracy: 10,
    });

    await page.goto("/report");
    await addPhotoFile(page, POTHOLE_PHOTO);
    await continueButton(page).click();
    await locateWithGps(page);
    await continueButton(page).click();

    // No suggestion comes; after the client gives up, the categories are
    // offered for a manual choice with nothing picked.
    await expect(
      page.getByRole("heading", { name: "What kind of problem is it?" }),
    ).toBeVisible();
    await expect(
      page.getByText("Looking at your photo to suggest a category…"),
    ).toBeHidden({ timeout: 45_000 });
    await expect(page.getByText("We picked this from your photo")).toHaveCount(
      0,
    );
    const choice = page.getByRole("radio", { name: /Pothole \/ road damage/ });
    await expect(choice).not.toBeChecked();
    await page.getByText("Pothole / road damage", { exact: true }).click();
    await expect(choice).toBeChecked();
    await fillPotholeDetails(
      page,
      `Pothole, AI down (AC-03, e2e ${Date.now()})`,
    );
    await continueButton(page).click();
    const reference = await sendReport(page);

    const mine = await api.myReports(citizen);
    const id = mine.items.find((item) => item.reference === reference)?.id;
    if (!id) throw new Error(`Report ${reference} isn't in My reports`);

    // Two minutes on, the watchdog matches it without the visual signal:
    // the same photo 4 m away goes to a person, not straight onto the
    // issue as it would with the model running (AC-04).
    const matched = await api.waitForMatching(citizen, id, 240_000);
    expect(matched.matching_status).toBe("review");
    expect(matched.issue).toBeNull();

    const operator = await api.login(staffPhone("aiDownOperator"));
    const staffView = await api.getReport(operator, id);
    const decision = staffView.match_decisions?.find(
      (d) => d.candidate_issue_id === existing.issue.id,
    );
    expect(decision?.decision).toBe("sent_to_review");
    expect(decision?.signals.reason).toBe("ai_unavailable");
    expect(decision?.signals.visual).toBeNull();

    // The citizen is told a person is checking.
    await page.goto(`/reports/${id}`);
    await expect(
      page.getByText("A member of staff is checking for similar reports"),
    ).toBeVisible();

    const task = await api.reviewTaskFor(operator, id);
    if (task) {
      await api.resolveReview(operator, task.id, {
        action: "link",
        issue_id: existing.issue.id,
      });
    }
  } finally {
    compose("start ai-worker");
    await waitForHealthyWorker();
  }
});
