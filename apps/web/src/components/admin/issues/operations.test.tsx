import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { IssueDetail } from "@/lib/api";
import { makeIssueDetail } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { OperationsCard } from "./operations-card";
import {
  ApproveClosureDialog,
  AssignDialog,
  NoteDialog,
  RejectClosureDialog,
} from "./operations-dialogs";

vi.mock("@/components/media/photo-gallery", () => ({
  PhotoGallery: ({ label }: { label: string }) => (
    <section aria-label={label} />
  ),
}));

const ASSIGNMENT = {
  id: "asg-1",
  team: { id: "team-1", name: "Roads North" },
  assignee: { id: "user-4", display_name: "Farah Field" },
  note: null,
  assigned_by: { id: "user-3", display_name: "Sunil Supervisor" },
  assigned_at: "2026-11-21T09:00:00+05:30",
  ended_at: null,
  end_reason: null,
  work_order: { id: "wo-1", state: "accepted" as const, version: 2 },
};

const CLOSURE = {
  id: "cr-1",
  state: "pending" as const,
  requested_by: { id: "user-4", display_name: "Farah Field" },
  requested_at: "2026-11-22T15:00:00+05:30",
  reason_code: null,
  note: "Patched with cold mix",
  after_photos: [],
  requires_approval: true,
  confirmations: 0,
  unresolved: 0,
};

const ELIGIBLE = [
  {
    team: { id: "team-1", name: "Roads North" },
    department: { id: "dept-roads", code: "ROADS", name: "Roads" },
    members: [
      {
        user: { id: "user-4", display_name: "Farah Field" },
        team_role: "lead",
      },
      {
        user: { id: "user-6", display_name: "Imran" },
        team_role: "member",
      },
    ],
  },
];

type DialogComponent = (props: {
  issue: IssueDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onReload: () => Promise<unknown>;
}) => React.ReactNode;

function Harness({
  Dialog,
  issue,
}: {
  Dialog: DialogComponent;
  issue: IssueDetail;
}) {
  const [open, setOpen] = useState(true);
  return (
    <>
      <Dialog
        issue={issue}
        open={open}
        onOpenChange={setOpen}
        onReload={async () => {}}
      />
      {open ? null : <p>Dialog closed</p>}
    </>
  );
}

describe("OperationsCard", () => {
  const noop = () => {};

  it("shows who has the issue and the pending fix with approve buttons", () => {
    renderWithProviders(
      <OperationsCard
        issue={makeIssueDetail({
          status: "pending_verification",
          operations: { assignment: ASSIGNMENT, closure_request: CLOSURE },
        })}
        canAssign
        canApprove
        onAssign={noop}
        onApprove={noop}
        onReject={noop}
      />,
    );
    expect(screen.getByText("Roads North")).toBeInTheDocument();
    expect(screen.getByText("Accepted")).toBeInTheDocument();
    expect(screen.getByText("Patched with cold mix")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Approve fix" }),
    ).toBeInTheDocument();
  });

  it("gives the photo similarity as advice when there's an after photo", () => {
    const photo = {
      id: "m-after",
      status: "ready" as const,
      thumb_url: null,
      display_url: null,
    };
    renderWithProviders(
      <OperationsCard
        issue={makeIssueDetail({
          status: "pending_verification",
          operations: {
            assignment: ASSIGNMENT,
            closure_request: {
              ...CLOSURE,
              after_photos: [photo],
              scene_match: { similarity: 0.873, model_id: "clip" },
            },
          },
        })}
        canAssign
        canApprove
        onAssign={noop}
        onApprove={noop}
        onReject={noop}
      />,
    );
    expect(
      screen.getByText(/look 87% like the reported photos/),
    ).toBeInTheDocument();
    expect(screen.getByText(/check the photos yourself/)).toBeInTheDocument();
  });

  it("hides assign and approve from staff without those permissions", () => {
    renderWithProviders(
      <OperationsCard
        issue={makeIssueDetail({
          status: "verified",
          operations: { assignment: null, closure_request: CLOSURE },
        })}
        canAssign={false}
        canApprove={false}
        onAssign={noop}
        onApprove={noop}
        onReject={noop}
      />,
    );
    expect(screen.getByText("Not assigned yet.")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Assign" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Approve fix" }),
    ).not.toBeInTheDocument();
  });

  it("offers no assignment for a status that can't be assigned", () => {
    renderWithProviders(
      <OperationsCard
        issue={makeIssueDetail({ status: "reported" })}
        canAssign
        canApprove
        onAssign={noop}
        onApprove={noop}
        onReject={noop}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Assign" }),
    ).not.toBeInTheDocument();
  });
});

describe("AssignDialog", () => {
  it("assigns to an eligible team member with the issue version", async () => {
    const assign = vi.fn();
    server.use(
      http.get(`${API}/issues/iss-1/eligible-teams`, () =>
        HttpResponse.json(ELIGIBLE),
      ),
      http.post(`${API}/issues/iss-1/assignments`, async ({ request }) => {
        assign(await request.json());
        return HttpResponse.json(
          makeIssueDetail({
            status: "assigned",
            operations: { assignment: ASSIGNMENT, closure_request: null },
          }),
          { status: 201 },
        );
      }),
    );
    const { user } = renderWithProviders(
      <Harness
        Dialog={AssignDialog}
        issue={makeIssueDetail({ status: "verified" })}
      />,
    );

    // The only eligible team is picked for you.
    expect(
      await screen.findByRole("radio", { name: /roads north/i }),
    ).toBeChecked();
    await user.selectOptions(screen.getByLabelText(/person/i), "user-4");
    await user.click(screen.getByRole("button", { name: "Assign" }));

    await screen.findByText("Dialog closed");
    expect(assign).toHaveBeenCalledWith({
      team_id: "team-1",
      assignee_id: "user-4",
      version: 3,
    });
  });

  it("needs a reason to reassign", async () => {
    const assign = vi.fn();
    server.use(
      http.get(`${API}/issues/iss-1/eligible-teams`, () =>
        HttpResponse.json(ELIGIBLE),
      ),
      http.post(`${API}/issues/iss-1/assignments`, async ({ request }) => {
        assign(await request.json());
        return HttpResponse.json(makeIssueDetail({ status: "assigned" }), {
          status: 201,
        });
      }),
    );
    const { user } = renderWithProviders(
      <Harness
        Dialog={AssignDialog}
        issue={makeIssueDetail({
          status: "in_progress",
          operations: { assignment: ASSIGNMENT, closure_request: null },
        })}
      />,
    );

    await screen.findByRole("radio", { name: /roads north/i });
    await user.click(screen.getByRole("button", { name: "Reassign" }));
    expect(screen.getByText("Reassigning needs a reason.")).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/^reason/i), "Farah is on leave");
    await user.click(screen.getByRole("button", { name: "Reassign" }));
    await screen.findByText("Dialog closed");
    expect(assign).toHaveBeenCalledWith({
      team_id: "team-1",
      assignee_id: null,
      reason: "Farah is on leave",
      version: 3,
    });
  });

  it("says so when no team can take the issue", async () => {
    server.use(
      http.get(`${API}/issues/iss-1/eligible-teams`, () =>
        HttpResponse.json([]),
      ),
    );
    renderWithProviders(
      <Harness
        Dialog={AssignDialog}
        issue={makeIssueDetail({ status: "verified" })}
      />,
    );
    expect(
      await screen.findByText("No team can take this issue"),
    ).toBeInTheDocument();
  });

  it("explains a refusal for an ineligible team", async () => {
    server.use(
      http.get(`${API}/issues/iss-1/eligible-teams`, () =>
        HttpResponse.json(ELIGIBLE),
      ),
      http.post(`${API}/issues/iss-1/assignments`, () =>
        HttpResponse.json(
          {
            error: {
              code: "team_not_eligible",
              message: "No",
              details: { reason: "inactive" },
            },
          },
          { status: 422 },
        ),
      ),
    );
    const { user } = renderWithProviders(
      <Harness
        Dialog={AssignDialog}
        issue={makeIssueDetail({ status: "verified" })}
      />,
    );
    await screen.findByRole("radio", { name: /roads north/i });
    await user.click(screen.getByRole("button", { name: "Assign" }));
    expect(
      await screen.findByText(/That team can't take this issue/),
    ).toBeInTheDocument();
  });
});

describe("closure dialogs", () => {
  const pending = makeIssueDetail({
    status: "pending_verification",
    operations: { assignment: ASSIGNMENT, closure_request: CLOSURE },
  });

  it("approves with an optional public note", async () => {
    const approve = vi.fn();
    server.use(
      http.post(`${API}/issues/iss-1/closure/approve`, async ({ request }) => {
        approve(await request.json());
        return HttpResponse.json(makeIssueDetail({ status: "resolved" }));
      }),
    );
    const { user } = renderWithProviders(
      <Harness Dialog={ApproveClosureDialog} issue={pending} />,
    );
    await user.type(
      screen.getByLabelText(/note for the citizens/i),
      "Filled and levelled",
    );
    await user.click(screen.getByRole("button", { name: "Approve fix" }));
    await screen.findByText("Dialog closed");
    expect(approve).toHaveBeenCalledWith({
      version: 3,
      public_note: "Filled and levelled",
    });
  });

  it("needs a reason to send the fix back", async () => {
    const reject = vi.fn();
    server.use(
      http.post(`${API}/issues/iss-1/closure/reject`, async ({ request }) => {
        reject(await request.json());
        return HttpResponse.json(makeIssueDetail({ status: "in_progress" }));
      }),
    );
    const { user } = renderWithProviders(
      <Harness Dialog={RejectClosureDialog} issue={pending} />,
    );
    await user.click(screen.getByRole("button", { name: "Send back" }));
    expect(screen.getByText("Say what still needs doing.")).toBeInTheDocument();
    expect(reject).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/^reason/i), "Edges still broken");
    await user.click(screen.getByRole("button", { name: "Send back" }));
    await screen.findByText("Dialog closed");
    expect(reject).toHaveBeenCalledWith({
      version: 3,
      reason: "Edges still broken",
    });
  });
});

describe("NoteDialog", () => {
  it("makes the author choose who sees the note", async () => {
    const note = vi.fn();
    server.use(
      http.post(`${API}/issues/iss-1/notes`, async ({ request }) => {
        note(await request.json());
        return HttpResponse.json(
          {
            id: "ev-9",
            at: "2026-11-22T10:00:00+05:30",
            type: "note",
            from_status: null,
            to_status: null,
            reason: "Contractor called",
            public_note: null,
            visibility: "internal",
            actor: null,
          },
          { status: 201 },
        );
      }),
      http.get(`${API}/issues/iss-1`, () =>
        HttpResponse.json(makeIssueDetail()),
      ),
    );
    const { user } = renderWithProviders(
      <Harness Dialog={NoteDialog} issue={makeIssueDetail()} />,
    );
    await user.type(screen.getByLabelText(/^note/i), "Contractor called");
    await user.click(screen.getByRole("button", { name: "Add note" }));
    expect(screen.getByText("Choose who sees the note.")).toBeInTheDocument();
    expect(note).not.toHaveBeenCalled();

    await user.click(screen.getByRole("radio", { name: /staff only/i }));
    await user.click(screen.getByRole("button", { name: "Add note" }));
    await screen.findByText("Dialog closed");
    expect(note).toHaveBeenCalledWith({
      body: "Contractor called",
      visibility: "internal",
    });
  });
});
