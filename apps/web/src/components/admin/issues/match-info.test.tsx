import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type MatchDecision, type StaffReport, session } from "@/lib/api";
import {
  makeAdmin,
  makeIssue,
  makeIssueDetail,
  makeReport,
} from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { makeSignals } from "@/test/signals";
import { MatchInfo } from "./match-info";
import { RelatedIssues } from "./related-issues";

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

function decision(overrides: Partial<MatchDecision> = {}): MatchDecision {
  return {
    id: "md-1",
    candidate_issue: { id: "iss-1", reference: "CP-26-000123" },
    rank: 1,
    score: 0.91,
    signals: makeSignals(),
    decision: "auto_linked",
    decided_by: null,
    decided_at: "2026-11-24T08:00:00Z",
    feedback: null,
    ...overrides,
  };
}

function report(overrides: Partial<StaffReport> = {}): StaffReport {
  const { issue: _issue, ...base } = makeReport();
  return {
    ...base,
    matching_status: "linked",
    match_decisions: [decision()],
    ...overrides,
  };
}

beforeEach(() =>
  session.setAuthenticated(
    "token",
    makeAdmin({ permissions: ["issue:read", "issue:triage", "issue:update"] }),
  ),
);
afterEach(() => session.reset());

describe("MatchInfo", () => {
  it("shows an automatic link, explains it on request, and records feedback", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post(`${API}/match-decisions/md-1/feedback`, async ({ request }) => {
        bodies.push(await request.json());
        return new HttpResponse(null, { status: 204 });
      }),
      http.get(`${API}/issues/iss-1`, () =>
        HttpResponse.json(makeIssueDetail()),
      ),
    );
    const { user } = renderWithProviders(
      <MatchInfo report={report()} issue={makeIssueDetail()} canGiveFeedback />,
    );

    expect(
      screen.getByText("Linked automatically (score 0.91)"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Why" }));
    expect(screen.getByRole("region", { name: "Match score" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Incorrect" }));
    expect(
      await screen.findByText("Marked as a wrong link"),
    ).toBeInTheDocument();
    expect(screen.getByText(/split this report out/)).toBeInTheDocument();
    expect(bodies).toEqual([{ correct: false }]);
  });

  it("shows feedback already given instead of the buttons", () => {
    renderWithProviders(
      <MatchInfo
        report={report({
          match_decisions: [decision({ feedback: "correct" })],
        })}
        issue={makeIssueDetail()}
        canGiveFeedback
      />,
    );
    expect(screen.getByText("Marked as a correct link")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Correct" })).toBeNull();
  });

  it("names the reviewer for a reviewed link and offers no auto-link feedback", () => {
    renderWithProviders(
      <MatchInfo
        report={report({
          match_decisions: [
            decision({
              decision: "chosen_by_reviewer",
              score: 0.72,
              decided_by: { id: "u2", display_name: "Ravi" },
            }),
          ],
        })}
        issue={makeIssueDetail()}
        canGiveFeedback
      />,
    );
    expect(
      screen.getByText("Linked by Ravi after review (score 0.72)"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Correct" })).toBeNull();
  });

  it("says when a report started the issue, with the closest other match", () => {
    renderWithProviders(
      <MatchInfo
        report={report({
          matching_status: "new_issue",
          match_decisions: [
            decision({
              decision: "rejected_candidate",
              score: 0.42,
              candidate_issue: { id: "iss-9", reference: "CP-26-000099" },
            }),
          ],
        })}
        issue={makeIssueDetail()}
        canGiveFeedback={false}
      />,
    );
    expect(screen.getByText(/started this issue/i)).toHaveTextContent(
      "The closest existing issue, CP-26-000099, scored 0.42.",
    );
  });
});

describe("RelatedIssues", () => {
  it("lists related issues with their notes and unlinks one", async () => {
    let removed = "";
    server.use(
      http.delete(`${API}/issues/iss-1/related/:other`, ({ params }) => {
        removed = String(params.other);
        return new HttpResponse(null, { status: 204 });
      }),
      http.get(`${API}/issues/iss-1`, () =>
        HttpResponse.json(makeIssueDetail()),
      ),
    );
    const { user } = renderWithProviders(
      <RelatedIssues
        canEdit
        issue={makeIssueDetail({
          related: [
            {
              issue: makeIssue({ id: "iss-4", reference: "CP-26-000104" }),
              note: "The burst main upstream",
            },
          ],
        })}
      />,
    );
    expect(screen.getByRole("link", { name: "CP-26-000104" })).toHaveAttribute(
      "href",
      "/admin/issues/iss-4",
    );
    expect(screen.getByText("The burst main upstream")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Unlink CP-26-000104" }),
    );
    expect(
      await screen.findByText("Unlinked CP-26-000104"),
    ).toBeInTheDocument();
    expect(removed).toBe("iss-4");
  });
});
