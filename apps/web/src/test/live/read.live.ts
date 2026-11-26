import { describe, expect, it } from "vitest";
import {
  getAiQuality,
  getCurrentTenant,
  getIssue,
  getIssuesGeoJson,
  getMatchingConfig,
  getMe,
  getPriorityConfig,
  getReport,
  getReviewTask,
  getUser,
  ISSUE_SORTS,
  isMergedIssue,
  listAdminCategories,
  listAuditEvents,
  listCategories,
  listDepartments,
  listIssues,
  listJurisdictions,
  listModels,
  listMyReports,
  listReviewTasks,
  listUsers,
  listWardBoundaries,
} from "@/lib/api";
import { signInAs } from "./sign-in";

/*
 * Every GET a Phase 0–2 screen makes, through the app's own endpoint
 * functions. A shape mismatch surfaces as ApiError("invalid_response")
 * with the zod issues in `cause`.
 */

function isoDay(offsetDays: number): string {
  const day = new Date(Date.now() + offsetDays * 86_400_000);
  return day.toISOString().slice(0, 10);
}

describe("citizen screens", () => {
  it("home, report flow and my reports", async () => {
    await signInAs("citizen");
    await getMe();
    await getCurrentTenant();
    expect((await listCategories()).length).toBeGreaterThan(0);
    const mine = await listMyReports({ limit: 50 });
    for (const report of mine.items.slice(0, 10)) {
      await getReport(report.id);
    }
  });
});

describe("operator screens", () => {
  it("work queue in every sort, and issue detail", async () => {
    await signInAs("operator");
    for (const sort of ISSUE_SORTS) {
      await listIssues({ sort, limit: 100 });
    }
    const page = await listIssues({ limit: 100 });
    expect(page.total).toBeGreaterThan(0);
    for (const issue of page.items) {
      const detail = await getIssue(issue.id);
      if (!isMergedIssue(detail)) expect(detail.id).toBe(issue.id);
    }
  });

  it("map: GeoJSON and ward boundaries", async () => {
    await signInAs("operator");
    const tenant = await getCurrentTenant();
    const bounds = tenant.map?.bounds ?? [-180, -85, 180, 85];
    await getIssuesGeoJson({ bbox: bounds });
    await listWardBoundaries();
  });

  it("review queue, open and resolved", async () => {
    await signInAs("operator");
    for (const status of ["open", "resolved"] as const) {
      const tasks = await listReviewTasks({ status, limit: 50 });
      for (const task of tasks.items) await getReviewTask(task.id);
    }
  });
});

describe("municipal admin screens", () => {
  it("users, departments, jurisdictions, audit", async () => {
    await signInAs("municipalAdmin");
    const users = await listUsers({ limit: 100 });
    for (const user of users.items.slice(0, 10)) await getUser(user.id);
    await listDepartments();
    await listJurisdictions({ kind: "ward" });
    await listAuditEvents({ limit: 100 });
  });

  it("categories and AI settings", async () => {
    await signInAs("municipalAdmin");
    await listAdminCategories();
    await getMatchingConfig();
    await getPriorityConfig();
    await listModels();
    await getAiQuality({ from: isoDay(-30), to: isoDay(0) });
  });
});
