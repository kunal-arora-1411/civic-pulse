import { screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { session } from "@/lib/api";
import { makeAdmin, makeIssue } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { IssuesScreen } from "./issues-screen";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
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
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const page = (items: unknown[]) => ({
  items,
  total: items.length,
  limit: 25,
  offset: 0,
});

const ISSUES = [
  makeIssue({ id: "iss-1", reference: "CP-26-000123", version: 3 }),
  makeIssue({ id: "iss-2", reference: "CP-26-000124", version: 5 }),
];

function mockLists() {
  server.use(
    http.get(`${API}/admin/categories`, () => HttpResponse.json(page([]))),
    http.get(`${API}/admin/jurisdictions`, () => HttpResponse.json(page([]))),
    http.get(`${API}/issues`, () => HttpResponse.json(page(ISSUES))),
  );
}

afterEach(() => {
  session.reset();
  window.history.replaceState(null, "", "/");
});

describe("bulk actions in the work queue", () => {
  it("changes the status of the selected issues after confirming, and reports each one", async () => {
    session.setAuthenticated(
      "token",
      makeAdmin({ permissions: ["issue:read", "issue:update"] }),
    );
    mockLists();
    const sent = vi.fn();
    server.use(
      http.post(`${API}/issues/bulk`, async ({ request }) => {
        sent(await request.json());
        return HttpResponse.json({
          succeeded: 1,
          failed: 1,
          results: [
            { issue_id: "iss-1", ok: true, error: null },
            { issue_id: "iss-2", ok: false, error: "version_conflict" },
          ],
        });
      }),
    );
    const { user } = renderWithProviders(<IssuesScreen />);

    await user.click(
      await screen.findByRole("checkbox", {
        name: "Select every issue on this page",
      }),
    );
    expect(screen.getByText("2 issues selected")).toBeInTheDocument();
    // Without issue:assign there's no bulk assignment.
    expect(
      screen.queryByRole("button", { name: "Assign" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Change status" }));
    const dialog = screen.getByRole("dialog");
    await user.selectOptions(
      within(dialog).getByLabelText(/new status/i),
      "verified",
    );
    await user.click(within(dialog).getByRole("button", { name: "Review" }));
    expect(
      within(dialog).getByText("Move 2 issues to “Verified”?"),
    ).toBeInTheDocument();
    expect(sent).not.toHaveBeenCalled();

    await user.click(
      within(dialog).getByRole("button", { name: "Apply to 2 issues" }),
    );

    expect(
      await within(dialog).findByText("1 changed, 1 not changed."),
    ).toBeInTheDocument();
    const results = within(dialog).getByRole("list", {
      name: "Result for each issue",
    });
    expect(
      within(results).getByText(/CP-26-000124/).parentElement,
    ).toHaveTextContent(/Someone else changed this/);
    expect(sent).toHaveBeenCalledWith({
      action: "status",
      items: [
        { issue_id: "iss-1", version: 3 },
        { issue_id: "iss-2", version: 5 },
      ],
      to_status: "verified",
      team_id: null,
      assignee_id: null,
      reason: null,
    });
  });

  it("offers no selection to staff who can't change issues", async () => {
    session.setAuthenticated(
      "token",
      makeAdmin({ permissions: ["issue:read"] }),
    );
    mockLists();
    renderWithProviders(<IssuesScreen />);

    await screen.findByRole("link", { name: "CP-26-000123" });
    expect(
      screen.queryByRole("checkbox", { name: /^Select/ }),
    ).not.toBeInTheDocument();
  });
});
