import { act, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReportDone } from "@/components/report/report-done";
import { session } from "@/lib/api";
import { makeReport, makeUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { ReportDetail } from "./report-detail";

vi.mock("@/components/map/lazy-maps", () => ({
  PinMap: ({ label }: { label: string }) => <section aria-label={label} />,
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

const base = makeReport();
const issue = base.issue;
if (!issue) throw new Error("fixture has an issue");
// Sent just now: after three minutes the page says matching is slow.
const created_at = new Date().toISOString();
const pending = makeReport({
  matching_status: "pending",
  issue: null,
  created_at,
});

beforeEach(() => {
  session.setAuthenticated("token", makeUser());
  server.use(http.get(`${API}/categories`, () => HttpResponse.json([])));
});
afterEach(() => session.reset());

/** The page unwraps its params with use(), so let it settle inside act. */
async function renderDetail() {
  const params = Promise.resolve({ id: "rep-1" });
  await act(async () => {
    renderWithProviders(
      <Suspense fallback={null}>
        <ReportDetail params={params} />
      </Suspense>,
    );
    await params;
  });
}

describe("matching status on the citizen's report", () => {
  it("polls while matching runs, then says which existing issue it joined", async () => {
    let calls = 0;
    server.use(
      http.get(`${API}/reports/rep-1`, () => {
        calls += 1;
        if (calls < 3) return HttpResponse.json(pending);
        return HttpResponse.json(
          makeReport({
            matching_status: "linked",
            issue: {
              ...issue,
              reference: "CP-26-000090",
              report_count: 4,
              unique_reporter_count: 3,
              timeline: [
                ...issue.timeline,
                {
                  at: "2026-11-24T09:00:00Z",
                  type: "merged",
                  from_status: null,
                  to_status: null,
                  public_note: null,
                },
              ],
            },
          }),
        );
      }),
    );
    await renderDetail();

    expect(
      await screen.findByText("Checking for similar reports…"),
    ).toBeInTheDocument();
    // The header shows a checking badge until there's an issue status.
    expect(
      screen.getByText("Checking for similar reports"),
    ).toBeInTheDocument();

    expect(
      await screen.findByText(
        "Added to an existing issue CP-26-000090",
        {},
        { timeout: 4000 },
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/3 people have reported this problem/),
    ).toBeInTheDocument();
    expect(calls).toBe(3);
    expect(
      screen.getByText("Combined with another report of the same problem"),
    ).toBeInTheDocument();
  });

  it("says a member of staff is checking while a review is open", async () => {
    server.use(
      http.get(`${API}/reports/rep-1`, () =>
        HttpResponse.json(
          makeReport({ matching_status: "review", issue: null, created_at }),
        ),
      ),
    );
    await renderDetail();
    expect(
      await screen.findByText(
        "A member of staff is checking for similar reports",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Being checked by staff")).toBeInTheDocument();
  });

  it("says matching is running late once it has taken minutes", async () => {
    server.use(
      http.get(`${API}/reports/rep-1`, () =>
        HttpResponse.json(
          makeReport({
            matching_status: "pending",
            issue: null,
            created_at: new Date(Date.now() - 10 * 60_000).toISOString(),
          }),
        ),
      ),
    );
    await renderDetail();
    expect(
      await screen.findByText("This is taking longer than usual"),
    ).toBeInTheDocument();
  });

  it("follows the confirmation from pending to a new issue", async () => {
    server.use(
      http.get(`${API}/reports/rep-1`, () =>
        HttpResponse.json(
          makeReport({
            matching_status: "new_issue",
            issue: { ...issue, reference: "CP-26-000124" },
          }),
        ),
      ),
    );
    renderWithProviders(<ReportDone report={pending} onAnother={() => {}} />);

    expect(
      screen.getByText("Checking for similar reports…"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(
        "New issue CP-26-000124 created",
        {},
        { timeout: 3000 },
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("You're the first to report this problem."),
    ).toBeInTheDocument();
  });
});
