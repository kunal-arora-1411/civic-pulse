import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import {
  freshCitizenPhone,
  type PendingReport,
  type Session,
} from "../support/api";
import { eastOf, freshSpot, POTHOLE_PHOTO } from "../support/env";
import { expect, test } from "../support/fixtures";
import { realModel, staffPhone } from "../support/staff";

/*
 * FR-036 at scale: many people report the same pothole at the same moment.
 * Matching runs on the AI worker and decides each report under an advisory
 * lock per (tenant, category family), so however the reports interleave,
 * exactly one issue may come out of it, with every report and every
 * reporter counted once.
 *
 * Runs in its own Playwright project after the others (playwright.config),
 * so the timings measure this burst rather than whatever else the worker
 * was doing. E2E_LOAD_REPORTS changes the size (default 50). The numbers
 * are printed and attached to the report; docs/eval/phase-2-matching-load.md
 * records a run.
 */

const REPORTS = Number(process.env.E2E_LOAD_REPORTS ?? 50);

test.skip(
  () => !realModel(),
  "needs the real vision model; this stack runs the fake one",
);

function percentile(sorted: number[], p: number): number {
  const index = Math.min(
    sorted.length - 1,
    Math.ceil((p / 100) * sorted.length) - 1,
  );
  return sorted[Math.max(0, index)] ?? Number.NaN;
}

test(`${REPORTS} simultaneous reports of one pothole make exactly one issue`, async ({
  api,
}, testInfo) => {
  test.setTimeout(600_000);
  const photo = await readFile(fileURLToPath(POTHOLE_PHOTO));
  const spot = freshSpot();

  // Arrange: one citizen each, signed in and with the photo uploaded,
  // so the burst is only the report submissions themselves.
  const citizens: { session: Session; mediaId: string }[] = [];
  for (let start = 0; start < REPORTS; start += 10) {
    const batch = await Promise.all(
      Array.from({ length: Math.min(10, REPORTS - start) }, async () => {
        const session = await api.login(freshCitizenPhone());
        return { session, mediaId: await api.uploadPhoto(session, photo) };
      }),
    );
    citizens.push(...batch);
  }

  // Act: every report at once, each within a metre or two of the spot.
  const sentAt = Date.now();
  const sent = await Promise.all(
    citizens.map(async ({ session, mediaId }, index) => {
      const report = await api.postReport(session, {
        categoryCode: "pothole",
        ...eastOf(spot, (index % 5) * 0.4),
        description: `Same pothole, reporter ${index + 1} (load e2e)`,
        mediaIds: [mediaId],
      });
      return { session, report, acceptedAt: Date.now() };
    }),
  );
  const submitMs = Date.now() - sentAt;

  // Wait for every decision, timing each from its own submission.
  const decided = await Promise.all(
    sent.map(async ({ session, report, acceptedAt }) => {
      const deadline = Date.now() + 300_000;
      let current: PendingReport = report;
      while (current.matching_status === "pending") {
        if (Date.now() > deadline) throw new Error(`${report.id} undecided`);
        await new Promise((resolve) => setTimeout(resolve, 250));
        current = await api.getReport(session, report.id);
      }
      return { report: current, latencyMs: Date.now() - acceptedAt };
    }),
  );
  const totalMs = Date.now() - sentAt;

  // Exactly one issue, which every report joined.
  const statuses = decided.map((d) => d.report.matching_status);
  expect(statuses.filter((s) => s === "new_issue")).toHaveLength(1);
  expect(statuses.filter((s) => s === "linked")).toHaveLength(REPORTS - 1);
  const issueIds = new Set(decided.map((d) => d.report.issue?.id));
  expect(issueIds.size).toBe(1);

  const operator = await api.login(staffPhone("loadOperator"));
  const issue = await api.getIssue(operator, [...issueIds][0] ?? "");
  expect(issue.report_count).toBe(REPORTS);
  expect(issue.unique_reporter_count).toBe(REPORTS);
  expect(issue.reports).toHaveLength(REPORTS);

  const latencies = decided.map((d) => d.latencyMs).sort((a, b) => a - b);
  const summary = {
    reports: REPORTS,
    submit_all_ms: submitMs,
    all_decided_ms: totalMs,
    latency_ms: {
      p50: percentile(latencies, 50),
      p90: percentile(latencies, 90),
      p95: percentile(latencies, 95),
      max: latencies.at(-1),
    },
    issue: issue.reference,
  };
  console.log(`matching under load: ${JSON.stringify(summary)}`);
  await testInfo.attach("matching-latency.json", {
    body: JSON.stringify(summary, null, 2),
    contentType: "application/json",
  });
});
