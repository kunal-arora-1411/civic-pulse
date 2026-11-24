import { screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { type Report, session } from "@/lib/api";
import { apiError } from "@/test/community";
import { makeReport, makeUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { ReopenButton, VerificationCard } from "./verification-card";

type Issue = NonNullable<Report["issue"]>;

const base = makeReport().issue as Issue;

function pending(overrides: Partial<Issue> = {}): Issue {
  return {
    ...base,
    status: "pending_verification",
    closure: {
      state: "pending",
      requested_at: "2026-11-23T10:00:00+05:30",
      reason_code: "contractor_done",
      after_photos: [
        {
          id: "after-1",
          status: "ready",
          thumb_url: "http://storage.test/after-thumb.webp",
          display_url: "http://storage.test/after.webp",
          original_url: null,
        },
      ],
    },
    can_verify: true,
    ...overrides,
  };
}

beforeEach(() => session.setAuthenticated("token", makeUser()));
afterEach(() => session.reset());

describe("VerificationCard", () => {
  it("shows the after photos and the closure note, and confirms a fix", async () => {
    let sent: unknown = null;
    server.use(
      http.post(`${API}/issues/iss-1/verification`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(
          makeReport({
            issue: pending({ can_verify: false, my_verification: "resolved" }),
          }),
        );
      }),
    );
    const { user, queryClient } = renderWithProviders(
      <VerificationCard reportId="rep-1" issue={pending()} />,
    );

    expect(
      screen.getByRole("heading", { name: "Is it fixed?" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Closure note: Contractor done")).toBeVisible();
    expect(
      screen.getByRole("button", { name: /open photo 1 of 1/i }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Yes, it's fixed" }));
    expect(await screen.findByText("Thanks for confirming")).toBeVisible();
    expect(sent).toEqual({ outcome: "resolved" });
    const stored = queryClient.getQueryData<Report>([
      "reports",
      "detail",
      "rep-1",
    ]);
    expect(stored?.issue?.my_verification).toBe("resolved");
  });

  it("requires a note before saying it's still broken", async () => {
    let sent: unknown = null;
    server.use(
      http.post(`${API}/issues/iss-1/verification`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeReport());
      }),
    );
    const { user } = renderWithProviders(
      <VerificationCard reportId="rep-1" issue={pending()} />,
    );

    await user.click(screen.getByRole("button", { name: "No, still broken" }));
    const submit = screen.getByRole("button", {
      name: "Send: still broken",
    });
    await user.click(submit);
    const note = screen.getByRole("textbox", { name: /what's still wrong/i });
    expect(note).toHaveAccessibleDescription(
      expect.stringContaining("Tell us what's still wrong."),
    );
    expect(sent).toBeNull();

    await user.type(note, "  Only half the pothole was filled ");
    await user.click(submit);
    expect(
      await screen.findByText("Thanks, we've sent it back to the municipality"),
    ).toBeVisible();
    expect(sent).toEqual({
      outcome: "unresolved",
      note: "Only half the pothole was filled",
    });
  });

  it.each([
    [
      409,
      "already_verified",
      "You've already answered for this round of work.",
    ],
    [
      403,
      "not_eligible",
      "Only people who reported this issue can confirm the fix.",
    ],
    [
      422,
      "invalid_transition",
      "This issue isn't waiting for confirmation any more. Reload to see where it is now.",
    ],
  ])("explains a %s %s", async (status, code, message) => {
    server.use(
      http.post(`${API}/issues/iss-1/verification`, () =>
        apiError(status, code),
      ),
      http.get(`${API}/reports/rep-1`, () => HttpResponse.json(makeReport())),
    );
    const { user } = renderWithProviders(
      <VerificationCard reportId="rep-1" issue={pending()} />,
    );
    await user.click(screen.getByRole("button", { name: "Yes, it's fixed" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("shows the citizen's earlier answer instead of the buttons", () => {
    renderWithProviders(
      <VerificationCard
        reportId="rep-1"
        issue={pending({ can_verify: false, my_verification: "unresolved" })}
      />,
    );
    expect(
      screen.getByText(
        "Thanks. You said it's still broken, so the municipality will look at it again.",
      ),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Yes, it's fixed" }),
    ).not.toBeInTheDocument();
  });

  it("renders nothing when there's nothing to verify", () => {
    renderWithProviders(<VerificationCard reportId="rep-1" issue={base} />);
    expect(
      screen.queryByRole("heading", { name: "Is it fixed?" }),
    ).not.toBeInTheDocument();
  });
});

describe("ReopenButton", () => {
  it("needs a reason, then reopens and stores the new report", async () => {
    let sent: unknown = null;
    server.use(
      http.post(`${API}/issues/iss-1/reopen`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(
          makeReport({ issue: { ...base, status: "reopened" } }),
        );
      }),
    );
    const { user, queryClient } = renderWithProviders(
      <ReopenButton reportId="rep-1" issueId="iss-1" />,
    );

    await user.click(screen.getByRole("button", { name: "Reopen this issue" }));
    const dialog = screen.getByRole("dialog", { name: "Reopen this issue" });
    await user.click(within(dialog).getByRole("button", { name: "Reopen" }));
    expect(
      within(dialog).getByText("Tell us why you're reopening it."),
    ).toBeVisible();
    expect(sent).toBeNull();

    await user.type(
      within(dialog).getByRole("textbox", { name: /why are you reopening/i }),
      "The pothole is back after the rain",
    );
    await user.click(within(dialog).getByRole("button", { name: "Reopen" }));
    expect(await screen.findByText("Issue reopened")).toBeVisible();
    expect(sent).toEqual({ reason: "The pothole is back after the rain" });
    expect(
      queryClient.getQueryData<Report>(["reports", "detail", "rep-1"])?.issue
        ?.status,
    ).toBe("reopened");
  });

  it("explains a refusal inside the dialog", async () => {
    server.use(
      http.post(`${API}/issues/iss-1/reopen`, () =>
        apiError(403, "not_eligible"),
      ),
    );
    const { user } = renderWithProviders(
      <ReopenButton reportId="rep-1" issueId="iss-1" />,
    );
    await user.click(screen.getByRole("button", { name: "Reopen this issue" }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByRole("textbox"), "Still broken");
    await user.click(within(dialog).getByRole("button", { name: "Reopen" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Only people who reported this issue can reopen it.",
    );
  });
});
