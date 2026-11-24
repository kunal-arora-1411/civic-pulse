import { describe, expect, it } from "vitest";
import {
  addRelatedIssue,
  changeIssueCategory,
  getIssue,
  getMatchingConfig,
  getMe,
  getPriorityConfig,
  type IssueDetail,
  isMergedIssue,
  listCategories,
  listIssues,
  listReviewTasks,
  mergeIssues,
  removeRelatedIssue,
  resolveReviewTask,
  setIssuePriority,
  setIssueSeverity,
  splitIssue,
  updateMatchingConfig,
  updatePriorityConfig,
} from "@/lib/api";
import { type PHONES, signInAs } from "./sign-in";

/*
 * Phase 2 write actions through the app's endpoint functions. Each test
 * undoes what it changes where the API allows it, so the seeded data
 * stays usable: overrides are cleared, the category is restored, the
 * related link is removed and configs are saved back unchanged. Merge is
 * undone by a split (the reports land in a new issue), and one open
 * review task is resolved.
 */

const STAFF = ["operator", "supervisor", "municipalAdmin"] as const;

/** Signs in as the first seeded staff role holding `permission`. */
async function signInWith(permission: string): Promise<keyof typeof PHONES> {
  for (const role of STAFF) {
    await signInAs(role);
    const me = await getMe();
    if (me.permissions.includes(permission)) return role;
  }
  throw new Error(`no seeded staff role has ${permission}`);
}

async function detail(id: string): Promise<IssueDetail> {
  const issue = await getIssue(id);
  if (isMergedIssue(issue)) throw new Error(`${id} is merged`);
  return issue;
}

const reason = "Live API check (B1.1)";

describe("issue detail actions", () => {
  // Priority needs issue:set_priority, severity only issue:update
  // (phase-2 contract), so each runs as a role that holds it.
  it("priority override, set then cleared", async () => {
    await signInWith("issue:set_priority");
    const [first] = (await listIssues({ limit: 1 })).items;
    if (!first) throw new Error("no issues seeded");
    let issue = await detail(first.id);

    issue = await setIssuePriority(issue.id, {
      band: "critical",
      reason,
      version: issue.version,
    });
    expect(issue.priority?.band).toBe("critical");
    await setIssuePriority(issue.id, {
      band: null,
      reason,
      version: issue.version,
    });
  });

  it("severity override, set then cleared", async () => {
    await signInWith("issue:update");
    const [first] = (await listIssues({ limit: 1 })).items;
    if (!first) throw new Error("no issues seeded");
    let issue = await detail(first.id);

    issue = await setIssueSeverity(issue.id, {
      severity: "high",
      reason,
      version: issue.version,
    });
    expect(issue.severity?.level).toBe("high");
    await setIssueSeverity(issue.id, {
      severity: null,
      reason,
      version: issue.version,
    });
  });

  it("category change, then restored", async () => {
    await signInWith("issue:update");
    const categories = await listCategories();
    const [first] = (await listIssues({ limit: 1, sort: "-created_at" })).items;
    if (!first) throw new Error("no issues seeded");
    let issue = await detail(first.id);
    const original = issue.category.id;
    const other = categories.find((category) => category.id !== original);
    if (!other) throw new Error("need two categories");

    issue = await changeIssueCategory(issue.id, {
      category_id: other.id,
      reason,
      version: issue.version,
    });
    expect(issue.category.id).toBe(other.id);
    await changeIssueCategory(issue.id, {
      category_id: original,
      reason,
      version: issue.version,
    });
  });

  it("related issues, added then removed", async () => {
    await signInWith("issue:update");
    const [a, b] = (await listIssues({ limit: 2 })).items;
    if (!a || !b) throw new Error("need two issues");
    await addRelatedIssue(a.id, { issue_id: b.id, note: reason });
    await removeRelatedIssue(a.id, b.id);
  });

  it("merge two issues, then split the reports back out", async () => {
    await signInWith("issue:merge");
    const items = (await listIssues({ limit: 100, sort: "created_at" })).items;
    // Two issues of the same category, so the merge is a realistic one.
    const pair = items.flatMap((x) =>
      items
        .filter((y) => y.id !== x.id && y.category.id === x.category.id)
        .map((y) => [x, y] as const),
    )[0];
    if (!pair) throw new Error("no two issues share a category");
    const [target, source] = pair;
    const before = await detail(source.id);
    const movedReports = before.reports.map((report) => report.id);

    const survivor = await detail(target.id);
    const merged = await mergeIssues(survivor.id, {
      source_issue_ids: [source.id],
      reason,
      version: survivor.version,
    });
    expect(merged.reports.map((r) => r.id)).toEqual(
      expect.arrayContaining(movedReports),
    );
    const tombstone = await getIssue(source.id);
    expect(isMergedIssue(tombstone)).toBe(true);

    const split = await splitIssue(merged.id, {
      report_ids: movedReports,
      target: { new_issue: true },
      reason,
      version: merged.version,
    });
    expect(split.target.reports.map((r) => r.id).sort()).toEqual(
      [...movedReports].sort(),
    );
  });
});

describe("review queue", () => {
  it("resolves one open task as a new issue", async () => {
    await signInWith("issue:triage");
    const open = await listReviewTasks({ status: "open", limit: 10 });
    const task = open.items[0];
    if (!task) return; // nothing left to review on this database
    const resolved = await resolveReviewTask(task.id, { action: "new_issue" });
    expect(resolved.report.issue).toBeTruthy();
  });
});

describe("settings", () => {
  it("matching and priority config round-trip unchanged", async () => {
    await signInWith("config:manage");
    const matching = await getMatchingConfig();
    expect(await updateMatchingConfig(matching)).toEqual(matching);
    const priority = await getPriorityConfig();
    expect(await updatePriorityConfig(priority)).toEqual(priority);
  });
});
