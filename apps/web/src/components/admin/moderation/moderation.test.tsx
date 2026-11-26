import { screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IssueComments } from "@/components/community/issue-comments";
import { session } from "@/lib/api";
import { makeAdmin, makeUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { ModerationScreen } from "./moderation-screen";

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

afterEach(() => session.reset());

const comment = (overrides: Record<string, unknown> = {}) => ({
  id: "c-1",
  issue_id: "iss-1",
  body: "Still flooding after rain",
  state: "approved",
  created_at: "2026-11-22T10:00:00+05:30",
  mine: false,
  flagged_by_me: false,
  author_name: null,
  flag_count: null,
  moderation_reason: null,
  ...overrides,
});

describe("IssueComments", () => {
  it("shows comments without their authors, and sends a new one for review", async () => {
    session.setAuthenticated("token", makeUser());
    const sent = vi.fn();
    server.use(
      http.get(`${API}/issues/iss-1/comments`, () =>
        HttpResponse.json({
          items: [
            comment(),
            comment({
              id: "c-2",
              mine: true,
              state: "rejected",
              body: "Call 98765",
              moderation_reason: "Personal details",
            }),
          ],
        }),
      ),
      http.post(`${API}/issues/iss-1/comments`, async ({ request }) => {
        sent(await request.json());
        return HttpResponse.json(
          comment({ id: "c-3", state: "pending", mine: true }),
          {
            status: 201,
          },
        );
      }),
    );
    const { user } = renderWithProviders(<IssueComments issueId="iss-1" />);

    const list = await screen.findByRole("list", { name: "Comments" });
    expect(within(list).getByText("A resident")).toBeInTheDocument();
    expect(
      within(list).getByText("Removed by a moderator: Personal details"),
    ).toBeInTheDocument();
    // Only other people's published comments can be reported.
    expect(
      within(list).getAllByRole("button", { name: "Report" }),
    ).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Send comment" }));
    expect(screen.getByText("Write your comment.")).toBeInTheDocument();
    expect(sent).not.toHaveBeenCalled();

    await user.type(
      screen.getByLabelText(/add a comment/i),
      "Water is knee deep",
    );
    await user.click(screen.getByRole("button", { name: "Send comment" }));
    expect(
      await screen.findByText(/will appear once a moderator has checked it/),
    ).toBeInTheDocument();
    expect(sent).toHaveBeenCalledWith({ body: "Water is knee deep" });
  });
});

describe("ModerationScreen", () => {
  const ENTRY = comment({
    state: "pending",
    author_name: "Asha Citizen",
    flag_count: 3,
    issue: { id: "iss-1", reference: "CP-26-000123" },
  });

  it("publishes a comment and removes another with a reason", async () => {
    session.setAuthenticated(
      "token",
      makeAdmin({ permissions: ["issue:read", "issue:update"] }),
    );
    const decisions: unknown[] = [];
    server.use(
      http.get(`${API}/moderation/comments`, () =>
        HttpResponse.json({ items: [ENTRY], total: 1, limit: 50, offset: 0 }),
      ),
      http.post(`${API}/moderation/comments/c-1`, async ({ request }) => {
        decisions.push(await request.json());
        return HttpResponse.json({ ...ENTRY, state: "approved" });
      }),
    );
    const { user } = renderWithProviders(<ModerationScreen />);

    const item = (await screen.findByText("Still flooding after rain")).closest(
      "li",
    ) as HTMLElement;
    expect(within(item).getByText("3 flags")).toBeInTheDocument();
    expect(
      within(item).getByRole("link", { name: "CP-26-000123" }),
    ).toHaveAttribute("href", "/admin/issues/iss-1");

    await user.click(within(item).getByRole("button", { name: "Publish" }));
    await vi.waitFor(() =>
      expect(decisions).toEqual([{ decision: "approve" }]),
    );

    await user.click(within(item).getByRole("button", { name: "Remove" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    expect(
      within(dialog).getByText("Say why it's removed."),
    ).toBeInTheDocument();
    await user.type(
      within(dialog).getByLabelText(/^reason/i),
      "Abusive language",
    );
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    await vi.waitFor(() =>
      expect(decisions).toEqual([
        { decision: "approve" },
        { decision: "reject", reason: "Abusive language" },
      ]),
    );
  });
});
