import { screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type IssueDetail, type Priority, session } from "@/lib/api";
import { makeAdmin, makeIssueDetail } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { PriorityDialog, SeverityDialog } from "./override-dialogs";
import { PriorityCard } from "./priority-card";

const priority: Priority = {
  score: 67.5,
  band: "high",
  computed_band: "high",
  overridden: false,
  override_reason: null,
  factors: [
    {
      factor: "severity",
      value: "high",
      normalized: 0.75,
      points: 30,
      explanation_key: "priority.severity",
    },
    {
      factor: "reporters",
      value: 3,
      normalized: 0.58,
      points: 11.6,
      explanation_key: "priority.reporters",
    },
    {
      factor: "near_places",
      value: true,
      normalized: 1,
      points: 10,
      explanation_key: "priority.near_places",
    },
    {
      factor: "community",
      value: 2,
      normalized: 0.5,
      points: 2.5,
      explanation_key: "priority.community",
    },
    {
      factor: "drainage_load",
      value: 0.2,
      normalized: 0.2,
      points: 1,
      explanation_key: "priority.drainage_load",
    },
  ],
};

const issue = (overrides: Partial<IssueDetail> = {}) =>
  makeIssueDetail({
    priority,
    severity: { level: "high", source: "rule", reason: null },
    ...overrides,
  });

beforeEach(() =>
  session.setAuthenticated(
    "token",
    makeAdmin({ permissions: ["issue:read", "issue:set_priority"] }),
  ),
);
afterEach(() => session.reset());

describe("PriorityCard", () => {
  it("explains the score factor by factor in words, with points", () => {
    renderWithProviders(
      <PriorityCard
        issue={issue()}
        canSetPriority
        canSetSeverity
        onOverridePriority={() => {}}
        onChangeSeverity={() => {}}
      />,
    );
    expect(screen.getByText("Score 67.5 of 100")).toBeInTheDocument();
    const factors = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(factors.map((li) => li.textContent)).toEqual([
      "Severity is High+30.0",
      "3 people have reported it+11.6",
      "Near a school, hospital or other sensitive place+10.0",
      "2 neighbours say they face this too+2.5",
      // A factor this client doesn't know yet still shows, by name.
      "Drainage load+1.0",
    ]);
    expect(screen.getByText("From the category's rules")).toBeInTheDocument();
  });

  it("shows an override with the computed band and the reason", () => {
    renderWithProviders(
      <PriorityCard
        issue={issue({
          priority: {
            ...priority,
            band: "critical",
            overridden: true,
            override_reason: "Outside the school gate",
          },
        })}
        canSetPriority={false}
        canSetSeverity={false}
        onOverridePriority={() => {}}
        onChangeSeverity={() => {}}
      />,
    );
    expect(
      screen.getByText("Set to Critical by hand. The rules give High."),
    ).toBeInTheDocument();
    expect(screen.getByText("Outside the school gate")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /override/i })).toBeNull();
  });
});

function Harness({
  initial,
  which,
}: {
  initial: IssueDetail;
  which: "priority" | "severity";
}) {
  const [open, setOpen] = useState(true);
  const Dialog = which === "priority" ? PriorityDialog : SeverityDialog;
  return (
    <>
      <Dialog
        issue={initial}
        open={open}
        onOpenChange={setOpen}
        onReload={vi.fn(async () => {})}
      />
      {open ? null : <p>Dialog closed</p>}
    </>
  );
}

describe("PriorityDialog", () => {
  it("requires a reason to override, and sends it with the version", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.patch(`${API}/issues/iss-1/priority`, async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(issue());
      }),
    );
    const { user } = renderWithProviders(
      <Harness initial={issue()} which="priority" />,
    );

    await user.click(screen.getByRole("radio", { name: /critical/i }));
    expect(screen.getByLabelText(/^reason/i)).toBeRequired();
    await user.click(screen.getByRole("button", { name: "Save priority" }));
    expect(
      screen.getByText("Say why you're overriding the priority."),
    ).toBeInTheDocument();
    expect(bodies).toEqual([]);

    await user.type(screen.getByLabelText(/^reason/i), "Next to a school");
    await user.click(screen.getByRole("button", { name: "Save priority" }));
    await screen.findByText("Dialog closed");
    expect(bodies).toEqual([
      { band: "critical", reason: "Next to a school", version: 3 },
    ]);
  });

  it("goes back to the computed band without needing a reason", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.patch(`${API}/issues/iss-1/priority`, async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(issue());
      }),
    );
    const { user } = renderWithProviders(
      <Harness
        initial={issue({
          priority: { ...priority, band: "low", overridden: true },
        })}
        which="priority"
      />,
    );
    await user.click(
      screen.getByRole("radio", { name: /go back to the computed band/i }),
    );
    expect(screen.getByLabelText(/reason \(optional\)/i)).not.toBeRequired();
    await user.click(screen.getByRole("button", { name: "Save priority" }));
    await screen.findByText("Dialog closed");
    expect(bodies).toEqual([{ band: null, reason: "", version: 3 }]);
  });

  it("explains a version conflict and offers a reload instead of retrying", async () => {
    let calls = 0;
    server.use(
      http.patch(`${API}/issues/iss-1/priority`, () => {
        calls += 1;
        return HttpResponse.json(
          {
            error: {
              code: "version_conflict",
              message: "",
              details: { version: 4 },
            },
          },
          { status: 409 },
        );
      }),
    );
    const { user } = renderWithProviders(
      <Harness initial={issue()} which="priority" />,
    );
    await user.click(screen.getByRole("radio", { name: /low/i }));
    await user.type(screen.getByLabelText(/^reason/i), "Fixed temporarily");
    await user.click(screen.getByRole("button", { name: "Save priority" }));

    expect(
      await screen.findByText(
        "This issue changed while you were looking at it",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Reload issue" }),
    ).toBeInTheDocument();
    expect(calls).toBe(1);
  });
});

describe("SeverityDialog", () => {
  it("overrides the severity with a reason", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.patch(`${API}/issues/iss-1/severity`, async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(issue());
      }),
    );
    const { user } = renderWithProviders(
      <Harness initial={issue()} which="severity" />,
    );
    await user.click(screen.getByRole("radio", { name: /^critical/i }));
    await user.click(screen.getByRole("button", { name: "Save severity" }));
    expect(
      screen.getByText("Say why you're overriding the severity."),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText(/^reason/i), "Exposed wires");
    await user.click(screen.getByRole("button", { name: "Save severity" }));
    await screen.findByText("Dialog closed");
    expect(bodies).toEqual([
      { severity: "critical", reason: "Exposed wires", version: 3 },
    ]);
  });
});
