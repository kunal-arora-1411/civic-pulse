import { screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type IssueDetail, session } from "@/lib/api";
import {
  makeAdmin,
  makeCategory,
  makeIssue,
  makeIssueDetail,
  makeReport,
} from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { CategoryDialog, MergeDialog, SplitDialog } from "./structure-dialogs";

const page = (items: unknown[]) => ({
  items,
  total: items.length,
  limit: 8,
  offset: 0,
});

function staffReport(id: string, reference: string) {
  const { issue: _issue, ...report } = makeReport({
    id,
    reference,
    reporter: { id: `u-${id}`, display_name: `Reporter ${id}` },
  });
  return { ...report, match_decisions: [] };
}

const survivor = makeIssueDetail({
  report_count: 2,
  reports: [
    staffReport("rep-1", "R-26-000301"),
    staffReport("rep-2", "R-26-000302"),
  ],
});

function Harness({
  Dialog,
  issue = survivor,
}: {
  Dialog: typeof MergeDialog;
  issue?: IssueDetail;
}) {
  const [open, setOpen] = useState(true);
  return (
    <>
      <Dialog
        issue={issue}
        open={open}
        onOpenChange={setOpen}
        onReload={vi.fn(async () => {})}
      />
      {open ? null : <p>Dialog closed</p>}
    </>
  );
}

beforeEach(() => {
  session.setAuthenticated(
    "token",
    makeAdmin({ permissions: ["issue:read", "issue:merge", "issue:update"] }),
  );
  server.use(
    http.get(`${API}/issues`, ({ request }) => {
      const q = new URL(request.url).searchParams.get("q") ?? "";
      return HttpResponse.json(
        page(
          [
            makeIssue(),
            makeIssue({
              id: "iss-7",
              reference: "CP-26-000107",
              report_count: 3,
            }),
            makeIssue({
              id: "iss-8",
              reference: "CP-26-000108",
              report_count: 1,
            }),
          ].filter((item) => item.reference.includes(q.toUpperCase())),
        ),
      );
    }),
  );
});
afterEach(() => session.reset());

describe("MergeDialog", () => {
  it("won't continue without an issue and a reason", async () => {
    const { user } = renderWithProviders(<Harness Dialog={MergeDialog} />);
    await user.click(screen.getByRole("button", { name: "Review the merge" }));
    expect(
      screen.getByText("Choose at least one issue to merge in."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Say why these are the same problem."),
    ).toBeInTheDocument();
  });

  it("searches, previews the combined count, and merges only after confirming", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post(`${API}/issues/iss-1/merge`, async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(makeIssueDetail({ report_count: 6 }));
      }),
    );
    const { user } = renderWithProviders(<Harness Dialog={MergeDialog} />);

    await user.type(screen.getByLabelText("Issues to merge in"), "cp-26");
    // The issue being edited is never offered.
    await screen.findByRole("checkbox", { name: "CP-26-000107" });
    expect(screen.queryByRole("checkbox", { name: "CP-26-000123" })).toBeNull();
    await user.click(screen.getByRole("checkbox", { name: "CP-26-000107" }));
    await user.click(screen.getByRole("checkbox", { name: "CP-26-000108" }));

    expect(
      screen.getByText(
        "CP-26-000123 will have 6 reports after merging: 4 reports from 2 issues.",
      ),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText(/^reason/i), "Same pothole");
    await user.click(screen.getByRole("button", { name: "Review the merge" }));

    // A confirmation step, and nothing sent yet.
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByRole("heading", {
        name: "Merge 2 issues into CP-26-000123?",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "4 reports move over from CP-26-000107, CP-26-000108.",
      ),
    ).toBeInTheDocument();
    expect(bodies).toEqual([]);

    // Back keeps what was chosen.
    await user.click(within(dialog).getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText(/^reason/i)).toHaveValue("Same pothole");
    await user.click(screen.getByRole("button", { name: "Review the merge" }));

    await user.click(screen.getByRole("button", { name: "Merge 2 issues" }));
    await screen.findByText("Dialog closed");
    expect(bodies).toEqual([
      {
        source_issue_ids: ["iss-7", "iss-8"],
        reason: "Same pothole",
        version: 3,
      },
    ]);
  });

  it("explains an invalid merge", async () => {
    server.use(
      http.post(`${API}/issues/iss-1/merge`, () =>
        HttpResponse.json(
          { error: { code: "invalid_merge", message: "" } },
          { status: 422 },
        ),
      ),
    );
    const { user } = renderWithProviders(<Harness Dialog={MergeDialog} />);
    await user.type(screen.getByLabelText("Issues to merge in"), "0107");
    await user.click(
      await screen.findByRole("checkbox", { name: "CP-26-000107" }),
    );
    await user.type(screen.getByLabelText(/^reason/i), "Same");
    await user.click(screen.getByRole("button", { name: "Review the merge" }));
    await user.click(screen.getByRole("button", { name: "Merge 1 issue" }));
    expect(
      await screen.findByText(/these issues can't be merged/i),
    ).toBeInTheDocument();
  });
});

describe("SplitDialog", () => {
  it("won't move every report off the issue", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post(`${API}/issues/iss-1/split`, async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json({
          source: survivor,
          target: makeIssueDetail({ id: "iss-9", reference: "CP-26-000109" }),
        });
      }),
    );
    const { user } = renderWithProviders(<Harness Dialog={SplitDialog} />);

    await user.click(screen.getByRole("checkbox", { name: /R-26-000301/ }));
    await user.click(screen.getByRole("checkbox", { name: /R-26-000302/ }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "At least one report has to stay on this issue.",
    );
    await user.type(screen.getByLabelText(/^reason/i), "Different drain");
    await user.click(screen.getByRole("button", { name: "Move 2 reports" }));
    expect(bodies).toEqual([]);

    await user.click(screen.getByRole("checkbox", { name: /R-26-000302/ }));
    expect(screen.queryByRole("alert")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Move 1 report" }));
    await screen.findByText("Dialog closed");
    expect(bodies).toEqual([
      {
        report_ids: ["rep-1"],
        target: { new_issue: true },
        reason: "Different drain",
        version: 3,
      },
    ]);
  });

  it("moves reports to an existing issue picked by search", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post(`${API}/issues/iss-1/split`, async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json({
          source: survivor,
          target: makeIssueDetail({ id: "iss-7", reference: "CP-26-000107" }),
        });
      }),
    );
    const { user } = renderWithProviders(<Harness Dialog={SplitDialog} />);
    await user.click(screen.getByRole("checkbox", { name: /R-26-000302/ }));
    await user.click(screen.getByRole("radio", { name: "An existing issue" }));
    await user.click(screen.getByRole("button", { name: "Move 1 report" }));
    expect(
      screen.getByText("Choose the issue to move them to."),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText("Issue to move them to"), "0107");
    await user.click(
      await screen.findByRole("radio", { name: "CP-26-000107" }),
    );
    await user.type(screen.getByLabelText(/^reason/i), "Belongs there");
    await user.click(screen.getByRole("button", { name: "Move 1 report" }));
    await screen.findByText("Dialog closed");
    expect(bodies[0]).toMatchObject({ target: { issue_id: "iss-7" } });
  });
});

describe("CategoryDialog", () => {
  it("offers the other categories and requires a reason", async () => {
    server.use(
      http.get(`${API}/categories`, () =>
        HttpResponse.json([
          makeCategory(),
          makeCategory({
            id: "cat-drain",
            code: "drainage",
            name_i18n: { en: "Blocked drain" },
          }),
        ]),
      ),
      http.patch(`${API}/issues/iss-1/category`, () =>
        HttpResponse.json(makeIssueDetail()),
      ),
    );
    const { user } = renderWithProviders(<Harness Dialog={CategoryDialog} />);
    const drain = await screen.findByRole("radio", { name: /blocked drain/i });
    expect(screen.queryByRole("radio", { name: /pothole/i })).toBeNull();
    await user.click(drain);
    await user.click(screen.getByRole("button", { name: "Change category" }));
    expect(
      screen.getByText("Say why the category was wrong."),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText(/^reason/i), "It's a drain");
    await user.click(screen.getByRole("button", { name: "Change category" }));
    expect(await screen.findByText("Dialog closed")).toBeInTheDocument();
  });
});
