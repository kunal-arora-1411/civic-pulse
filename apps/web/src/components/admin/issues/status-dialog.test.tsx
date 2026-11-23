import { screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { IssueDetail } from "@/lib/api";
import { makeIssueDetail } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { StatusDialog } from "./status-dialog";

function Harness({
  issue,
  onReload = vi.fn(async () => {}),
}: {
  issue: IssueDetail;
  onReload?: () => Promise<unknown>;
}) {
  const [open, setOpen] = useState(true);
  return (
    <>
      <StatusDialog
        issue={issue}
        open={open}
        onOpenChange={setOpen}
        onReload={onReload}
      />
      {open ? null : <p>Dialog closed</p>}
    </>
  );
}

describe("StatusDialog", () => {
  it("lists only the allowed transitions", () => {
    renderWithProviders(<Harness issue={makeIssueDetail()} />);
    const radios = screen
      .getAllByRole("radio")
      .map((radio) =>
        radio.closest("label")?.textContent?.replace("Reason required", ""),
      );
    expect(radios).toEqual(["Under review", "Verified", "Rejected"]);
  });

  it("requires a reason when the transition does, before calling the API", async () => {
    const patch = vi.fn();
    server.use(
      http.patch(`${API}/issues/iss-1/status`, async ({ request }) => {
        patch(await request.json());
        return HttpResponse.json(makeIssueDetail({ status: "rejected" }));
      }),
    );
    const { user } = renderWithProviders(<Harness issue={makeIssueDetail()} />);

    await user.click(screen.getByRole("radio", { name: /rejected/i }));
    expect(screen.getByLabelText(/^reason/i)).toBeRequired();
    await user.click(screen.getByRole("button", { name: "Change status" }));

    expect(screen.getByText("This change needs a reason.")).toBeInTheDocument();
    expect(patch).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/^reason/i), "Duplicate report");
    await user.type(
      screen.getByLabelText(/note for the citizen/i),
      "Already being fixed under CP-26-000100.",
    );
    await user.click(screen.getByRole("button", { name: "Change status" }));

    await screen.findByText("Dialog closed");
    expect(patch).toHaveBeenCalledWith({
      to_status: "rejected",
      reason: "Duplicate report",
      public_note: "Already being fixed under CP-26-000100.",
      version: 3,
    });
  });

  it("doesn't ask for a reason when the transition doesn't need one", async () => {
    server.use(
      http.patch(`${API}/issues/iss-1/status`, () =>
        HttpResponse.json(makeIssueDetail({ status: "verified" })),
      ),
    );
    const { user } = renderWithProviders(<Harness issue={makeIssueDetail()} />);
    await user.click(screen.getByRole("radio", { name: /verified/i }));
    expect(screen.getByLabelText(/reason \(optional\)/i)).not.toBeRequired();
    await user.click(screen.getByRole("button", { name: "Change status" }));
    expect(await screen.findByText("Dialog closed")).toBeInTheDocument();
  });

  it("shows a reload state on a version conflict instead of overwriting", async () => {
    let calls = 0;
    server.use(
      http.patch(`${API}/issues/iss-1/status`, () => {
        calls += 1;
        return HttpResponse.json(
          {
            error: {
              code: "version_conflict",
              message: "Version mismatch",
              details: { version: 4 },
            },
          },
          { status: 409 },
        );
      }),
    );
    const onReload = vi.fn(async () => {});
    const { user } = renderWithProviders(
      <Harness issue={makeIssueDetail()} onReload={onReload} />,
    );

    await user.click(screen.getByRole("radio", { name: /verified/i }));
    await user.type(screen.getByLabelText(/^reason/i), "Checked on site");
    await user.click(screen.getByRole("button", { name: "Change status" }));

    expect(
      await screen.findByText(
        "This issue changed while you were looking at it",
      ),
    ).toBeInTheDocument();
    expect(calls).toBe(1);
    expect(screen.queryByRole("button", { name: "Change status" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Reload issue" }));
    expect(onReload).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.getAllByRole("radio")).toHaveLength(3));
    // What the user typed survives the reload; no second request was sent.
    expect(screen.getByLabelText(/^reason/i)).toHaveValue("Checked on site");
    expect(calls).toBe(1);
  });
});
