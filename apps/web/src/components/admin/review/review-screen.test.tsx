import { screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type ReviewTask, session } from "@/lib/api";
import { makeAdmin, makeIssue, makeReport } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { makeSignals } from "@/test/signals";
import { ReviewScreen } from "./review-screen";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock("@/components/map/lazy-maps", () => ({
  ComparisonMap: ({ label }: { label: string }) => (
    <section aria-label={label} />
  ),
  MapSkeleton: () => null,
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({
    href,
    children,
    ...props
  }: { href: string } & Record<string, unknown>) => (
    <a href={href} {...props}>
      {children as React.ReactNode}
    </a>
  ),
}));

function task(id: string, reference: string, candidates = 2): ReviewTask {
  const { issue: _issue, ...report } = makeReport({
    id: `rep-${id}`,
    reference,
    matching_status: "review",
    reporter: { id: "u5", display_name: "Asha" },
  });
  return {
    id,
    created_at: "2026-11-24T08:00:00Z",
    status: "open",
    report: { ...report, view: "staff", match_decisions: [] },
    candidates: Array.from({ length: candidates }, (_, i) => ({
      match_decision_id: `md-${id}-${i}`,
      score: i === 0 ? 0.78 : 0.64,
      signals: makeSignals(),
      issue: makeIssue({
        id: `iss-${id}-${i}`,
        reference: `CP-26-00010${i}`,
        report_count: 3,
        unique_reporter_count: 2,
      }),
    })),
  };
}

const page = (items: ReviewTask[]) => ({
  items,
  total: items.length,
  limit: 50,
  offset: 0,
});

let tasks: ReviewTask[];
const resolved: { id: string; body: unknown }[] = [];

beforeEach(() => {
  session.setAuthenticated(
    "token",
    makeAdmin({ permissions: ["issue:read", "issue:triage"] }),
  );
  window.history.replaceState(null, "", "/admin/review");
  tasks = [task("rt-1", "R-26-000201"), task("rt-2", "R-26-000202", 1)];
  resolved.length = 0;
  server.use(
    http.get(`${API}/review-tasks`, () => HttpResponse.json(page(tasks))),
    http.post(
      `${API}/review-tasks/:id/resolve`,
      async ({ params, request }) => {
        const id = String(params.id);
        resolved.push({ id, body: await request.json() });
        tasks = tasks.filter((item) => item.id !== id);
        return HttpResponse.json({ id, status: "resolved" });
      },
    ),
  );
});
afterEach(() => session.reset());

describe("ReviewScreen", () => {
  it("opens the first report side by side with its best match and the reasons", async () => {
    renderWithProviders(<ReviewScreen />);

    expect(
      await screen.findByRole("heading", { name: "R-26-000201 (1 of 2)" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "2 reports to review" }),
    ).toBeInTheDocument();
    const task = screen.getByRole("region", { name: "R-26-000201 (1 of 2)" });
    expect(within(task).getByText("New report")).toBeInTheDocument();
    expect(
      within(task).getByRole("link", { name: "CP-26-000100" }),
    ).toHaveAttribute("href", "/admin/issues/iss-rt-1-0");
    expect(
      within(task).getByRole("region", {
        name: "Map comparing R-26-000201 with CP-26-000100",
      }),
    ).toBeInTheDocument();
    expect(
      within(task).getByText(
        "18 m apart. The category's matching radius is 30 m.",
      ),
    ).toBeInTheDocument();
    expect(
      within(task).getByRole("region", { name: "Match score" }),
    ).toHaveTextContent("0.78");
    // Each action shows its shortcut.
    expect(
      within(task).getByRole("button", {
        name: /same problem: add to CP-26-000100/i,
      }),
    ).toHaveAttribute("aria-keyshortcuts", "L");
  });

  it("links the report to the chosen candidate and moves on to the next one", async () => {
    const { user } = renderWithProviders(<ReviewScreen />);
    await screen.findByRole("heading", { name: "R-26-000201 (1 of 2)" });

    await user.click(screen.getByRole("radio", { name: /CP-26-000101/ }));
    await user.click(
      screen.getByRole("button", {
        name: /same problem: add to CP-26-000101/i,
      }),
    );

    expect(
      await screen.findByText("R-26-000201 added to CP-26-000101"),
    ).toBeInTheDocument();
    expect(resolved).toEqual([
      { id: "rt-1", body: { action: "link", issue_id: "iss-rt-1-1" } },
    ]);
    expect(
      await screen.findByRole("heading", { name: "R-26-000202 (1 of 1)" }),
    ).toBeInTheDocument();
    expect(window.location.search).toBe("?task=rt-2");
  });

  it("works from the keyboard: 2 picks a candidate, N makes a new issue", async () => {
    const { user } = renderWithProviders(<ReviewScreen />);
    await screen.findByRole("heading", { name: "R-26-000201 (1 of 2)" });

    await user.keyboard("2");
    expect(screen.getByRole("radio", { name: /CP-26-000101/ })).toBeChecked();
    await user.keyboard("j");
    expect(
      screen.getByRole("heading", { name: "R-26-000202 (2 of 2)" }),
    ).toBeInTheDocument();
    await user.keyboard("n");

    await waitFor(() =>
      expect(resolved).toEqual([{ id: "rt-2", body: { action: "new_issue" } }]),
    );
    expect(
      await screen.findByText("R-26-000202 is now an issue of its own"),
    ).toBeInTheDocument();
  });

  it("says so when someone else resolved the report first, and moves on", async () => {
    server.use(
      http.post(`${API}/review-tasks/rt-1/resolve`, () => {
        // A colleague got there first.
        tasks = tasks.filter((item) => item.id !== "rt-1");
        return HttpResponse.json(
          { error: { code: "conflict", message: "Already resolved" } },
          { status: 409 },
        );
      }),
    );
    const { user } = renderWithProviders(<ReviewScreen />);
    await screen.findByRole("heading", { name: "R-26-000201 (1 of 2)" });

    await user.click(
      screen.getByRole("button", { name: /different problem: new issue/i }),
    );

    expect(
      await screen.findByText("Someone else already dealt with this report"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /different problem/i }),
    ).toBeNull();
    // Shortcuts are off while the notice is up.
    await user.keyboard("n");

    await user.click(
      screen.getByRole("button", { name: "Show the next report" }),
    );
    expect(
      await screen.findByRole("heading", { name: "R-26-000202 (1 of 1)" }),
    ).toBeInTheDocument();
  });

  it("shows a calm empty state when nothing is waiting", async () => {
    tasks = [];
    renderWithProviders(<ReviewScreen />);
    expect(await screen.findByText("Nothing to review")).toBeInTheDocument();
  });
});
