import { screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { session } from "@/lib/api";
import { groupByDay } from "@/lib/notifications/hooks";
import { makeUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { NotificationBell } from "./notification-bell";

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

const now = new Date();
const yesterday = new Date(now.getTime() - 36 * 3600 * 1000);

function note(overrides: Record<string, unknown>) {
  return {
    id: "n-1",
    kind: "issue_status",
    title_key: "issue_status.title",
    body_key: "issue_status.body",
    params: { issue: "CP-26-000042", status: "in_progress" },
    link: "/reports/rep-1",
    issue_id: "iss-1",
    read_at: null,
    created_at: now.toISOString(),
    ...overrides,
  };
}

let unread = 1;
let readIds: string[] = [];
let readAll = 0;

beforeEach(() => {
  unread = 1;
  readIds = [];
  readAll = 0;
  session.setAuthenticated("token", makeUser());
  server.use(
    http.get(`${API}/notifications/unread-count`, () =>
      HttpResponse.json({ unread }),
    ),
    http.get(`${API}/notifications`, () =>
      HttpResponse.json({
        items: [
          note({}),
          note({
            id: "n-2",
            kind: "report_new_issue",
            title_key: "report_new_issue.title",
            body_key: "report_new_issue.body",
            params: { issue: "CP-26-000042", report: "R-26-000099" },
            read_at: yesterday.toISOString(),
            created_at: yesterday.toISOString(),
          }),
        ],
        total: 2,
        limit: 8,
        offset: 0,
        unread,
      }),
    ),
    http.post(`${API}/notifications/:id/read`, ({ params }) => {
      readIds.push(String(params.id));
      unread = 0;
      return HttpResponse.json(note({ read_at: now.toISOString() }));
    }),
    http.post(`${API}/notifications/read-all`, () => {
      readAll += 1;
      const updated = unread;
      unread = 0;
      return HttpResponse.json({ updated });
    }),
  );
});
afterEach(() => session.reset());

describe("NotificationBell", () => {
  it("announces the unread count and opens a grouped panel", async () => {
    const { user } = renderWithProviders(<NotificationBell />);
    const bell = await screen.findByRole("button", {
      name: "Notifications, 1 unread",
    });
    expect(bell).toHaveAttribute("aria-expanded", "false");

    await user.click(bell);
    expect(bell).toHaveAttribute("aria-expanded", "true");
    const panel = screen.getByRole("region", { name: "Notifications" });
    const today = await within(panel).findByRole("region", { name: "Today" });
    const row = within(today).getByRole("link", {
      name: /Issue CP-26-000042: In progress/,
    });
    expect(row).toHaveAttribute("href", "/reports/rep-1");
    expect(row).toHaveTextContent("Unread");
    const earlier = within(panel).getByRole("region", { name: "Earlier" });
    expect(
      within(earlier).getByText("Report R-26-000099 is now issue CP-26-000042"),
    ).toBeInTheDocument();

    await user.click(row);
    await waitFor(() => expect(readIds).toEqual(["n-1"]));
  });

  it("marks everything read and closes on Escape", async () => {
    const { user } = renderWithProviders(<NotificationBell />);
    const bell = await screen.findByRole("button", { name: /1 unread/ });
    await user.click(bell);
    await user.click(
      await screen.findByRole("button", { name: "Mark all read" }),
    );
    await waitFor(() => expect(readAll).toBe(1));
    await screen.findByRole("button", { name: "Notifications" });

    await user.keyboard("{Escape}");
    expect(bell).toHaveAttribute("aria-expanded", "false");
    expect(bell).toHaveFocus();
  });

  it("renders nothing for signed-out visitors", () => {
    session.reset();
    renderWithProviders(<NotificationBell />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("groupByDay", () => {
  it("splits on the reader's local midnight", () => {
    const at = new Date(2026, 10, 24, 9, 0);
    const items = [
      note({ id: "a", created_at: new Date(2026, 10, 24, 0, 5).toISOString() }),
      note({
        id: "b",
        created_at: new Date(2026, 10, 23, 23, 55).toISOString(),
      }),
    ];
    const { today, earlier } = groupByDay(items, at);
    expect(today.map((i) => i.id)).toEqual(["a"]);
    expect(earlier.map((i) => i.id)).toEqual(["b"]);
  });
});
