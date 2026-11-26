import { screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { session } from "@/lib/api";
import { makeAdmin, makeUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { AnnouncementsScreen } from "./announcements-screen";

const page = (items: unknown[]) => ({
  items,
  total: items.length,
  limit: 50,
  offset: 0,
});

const announcement = (overrides: Record<string, unknown> = {}) => ({
  id: "a1",
  kind: "planned_works",
  title_i18n: { en: "Road resurfacing", hi: "सड़क मरम्मत" },
  body_i18n: { en: "Main Road is closed overnight." },
  ward: { id: "w1", code: "W01", name: "Ward 1" },
  category: null,
  starts_at: "2026-11-26T12:30:00Z",
  ends_at: "2026-11-28T00:30:00Z",
  state: "active",
  withdrawn_at: null,
  created_by: { id: "u1", display_name: "Meera Admin" },
  created_at: "2026-11-26T10:00:00Z",
  updated_at: "2026-11-26T10:00:00Z",
  ...overrides,
});

let listed: URL[] = [];
let created: Record<string, unknown> | null = null;
let withdrawn: string | null = null;

beforeEach(() => {
  listed = [];
  created = null;
  withdrawn = null;
  session.setAuthenticated("token", makeAdmin());
  server.use(
    http.get(`${API}/admin/announcements`, ({ request }) => {
      listed.push(new URL(request.url));
      return HttpResponse.json(page([announcement()]));
    }),
    http.post(`${API}/admin/announcements`, async ({ request }) => {
      created = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json(announcement({ id: "a2" }), { status: 201 });
    }),
    http.post(`${API}/admin/announcements/:id/withdraw`, ({ params }) => {
      withdrawn = String(params.id);
      return HttpResponse.json(
        announcement({
          state: "withdrawn",
          withdrawn_at: "2026-11-26T13:00:00Z",
        }),
      );
    }),
    http.get(`${API}/admin/categories`, () => HttpResponse.json(page([]))),
    http.get(`${API}/admin/jurisdictions`, () =>
      HttpResponse.json(
        page([
          {
            id: "w1",
            parent_id: null,
            kind: "ward",
            name: "Ward 1",
            code: "W01",
          },
        ]),
      ),
    ),
  );
});

afterEach(() => session.reset());

async function openCreate() {
  const rendered = renderWithProviders(<AnnouncementsScreen />);
  await rendered.user.click(
    await screen.findByRole("button", { name: "New announcement" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "New announcement",
  });
  return { user: rendered.user, dialog: within(dialog) };
}

describe("AnnouncementsScreen", () => {
  it("lists announcements with their area, IST times and state", async () => {
    renderWithProviders(<AnnouncementsScreen />);

    const row = (await screen.findByText("Road resurfacing")).closest("tr");
    expect(row).not.toBeNull();
    const cells = within(row as HTMLElement);
    expect(cells.getByText("Planned works")).toBeInTheDocument();
    expect(cells.getByText("Ward 1")).toBeInTheDocument();
    expect(cells.getByText("Showing now")).toBeInTheDocument();
    // 12:30 UTC is 6:00 PM in India.
    expect(row).toHaveTextContent(/6:00\s?PM/);
  });

  it("filters by state", async () => {
    const { user } = renderWithProviders(<AnnouncementsScreen />);
    await screen.findByText("Road resurfacing");

    await user.selectOptions(screen.getByLabelText("Show"), "scheduled");

    await waitFor(() =>
      expect(listed.at(-1)?.searchParams.get("state")).toBe("scheduled"),
    );
  });

  it("publishes a new announcement with times read as IST", async () => {
    const { user, dialog } = await openCreate();

    await user.selectOptions(dialog.getByLabelText("Type"), "outage");
    await user.type(
      dialog.getByLabelText(/^Title \(English\)/),
      "Water outage",
    );
    await user.type(
      dialog.getByLabelText(/^Message \(English\)/),
      "No supply 10am to 2pm.",
    );
    const starts = dialog.getByLabelText(/^Starts/);
    await user.clear(starts);
    await user.type(starts, "2026-11-27T10:00");
    const ends = dialog.getByLabelText(/^Ends/);
    await user.clear(ends);
    await user.type(ends, "2026-11-27T14:00");
    await user.click(dialog.getByRole("button", { name: "Publish" }));

    await waitFor(() => expect(created).not.toBeNull());
    expect(created).toEqual({
      kind: "outage",
      title_i18n: { en: "Water outage" },
      body_i18n: { en: "No supply 10am to 2pm." },
      ward_id: null,
      category_id: null,
      starts_at: "2026-11-27T04:30:00.000Z",
      ends_at: "2026-11-27T08:30:00.000Z",
    });
  });

  it("needs English text and an end after the start", async () => {
    const { user, dialog } = await openCreate();
    const ends = dialog.getByLabelText(/^Ends/);
    await user.clear(ends);
    await user.type(ends, "2020-01-01T00:00");
    await user.click(dialog.getByRole("button", { name: "Publish" }));

    expect(dialog.getByText("Enter an English title.")).toBeInTheDocument();
    expect(
      dialog.getByText("The end must be after the start."),
    ).toBeInTheDocument();
    expect(created).toBeNull();
  });

  it("withdraws after confirmation", async () => {
    const { user } = renderWithProviders(<AnnouncementsScreen />);
    await user.click(
      await screen.findByRole("button", {
        name: "Withdraw “Road resurfacing”",
      }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Withdraw “Road resurfacing”?",
    });
    await user.click(within(dialog).getByRole("button", { name: "Withdraw" }));

    await waitFor(() => expect(withdrawn).toBe("a1"));
  });

  it("is read-only without config:manage", async () => {
    session.setAuthenticated(
      "token",
      makeUser({ is_staff: true, permissions: ["config:read"] }),
    );
    renderWithProviders(<AnnouncementsScreen />);

    await screen.findByText("Road resurfacing");
    expect(
      screen.queryByRole("button", { name: "New announcement" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Withdraw/ }),
    ).not.toBeInTheDocument();
  });
});
