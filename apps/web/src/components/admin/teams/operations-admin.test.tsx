import { screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ClosureSettings } from "@/components/admin/settings/closure-settings";
import { WorkloadScreen } from "@/components/admin/workload/workload-screen";
import { session } from "@/lib/api";
import { makeAdmin, makeTeam } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { TeamsScreen } from "./teams-screen";

afterEach(() => session.reset());

function signIn(permissions: string[]) {
  session.setAuthenticated("token", makeAdmin({ permissions }));
}

const TEAMS = { items: [makeTeam()], total: 1, limit: 100, offset: 0 };

describe("TeamsScreen", () => {
  it("lists teams with their lead and status", async () => {
    signIn(["config:read", "config:manage"]);
    server.use(http.get(`${API}/admin/teams`, () => HttpResponse.json(TEAMS)));
    renderWithProviders(<TeamsScreen />);

    const row = (await screen.findByText("Roads North")).closest("tr");
    expect(row).not.toBeNull();
    expect(
      within(row as HTMLElement).getByText("Farah Field (lead)"),
    ).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("Active")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "New team" }),
    ).toBeInTheDocument();
  });

  it("is read-only without config:manage", async () => {
    signIn(["config:read"]);
    server.use(http.get(`${API}/admin/teams`, () => HttpResponse.json(TEAMS)));
    renderWithProviders(<TeamsScreen />);

    await screen.findByText("Roads North");
    expect(
      screen.queryByRole("button", { name: "New team" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edit Roads North" }),
    ).not.toBeInTheDocument();
  });

  it("explains why a team with open work can't be deactivated", async () => {
    signIn(["config:read", "config:manage"]);
    const patch = vi.fn();
    server.use(
      http.get(`${API}/admin/teams`, () => HttpResponse.json(TEAMS)),
      http.get(`${API}/admin/departments`, () =>
        HttpResponse.json({ items: [], total: 0, limit: 100, offset: 0 }),
      ),
      http.get(`${API}/admin/jurisdictions`, () =>
        HttpResponse.json({ items: [], total: 0, limit: 100, offset: 0 }),
      ),
      http.get(`${API}/admin/categories`, () =>
        HttpResponse.json({ items: [], total: 0, limit: 100, offset: 0 }),
      ),
      http.get(`${API}/admin/users`, () =>
        HttpResponse.json({ items: [], total: 0, limit: 100, offset: 0 }),
      ),
      http.patch(`${API}/admin/teams/team-1`, async ({ request }) => {
        patch(await request.json());
        return HttpResponse.json(
          { error: { code: "team_has_open_work", message: "Open work" } },
          { status: 409 },
        );
      }),
    );
    const { user } = renderWithProviders(<TeamsScreen />);

    await user.click(
      await screen.findByRole("button", { name: "Edit Roads North" }),
    );
    await user.click(
      await screen.findByLabelText("Active: can be assigned new work"),
    );
    await user.click(screen.getByRole("button", { name: "Save team" }));

    expect(
      await screen.findByText(/still has open work orders/),
    ).toBeInTheDocument();
    expect(patch).toHaveBeenCalledWith(
      expect.objectContaining({
        is_active: false,
        members: [{ user_id: "user-4", team_role: "lead" }],
        jurisdiction_ids: ["zone-north"],
        category_ids: ["cat-pothole"],
      }),
    );
  });
});

describe("WorkloadScreen", () => {
  it("shows open work per team and member", async () => {
    signIn(["issue:assign"]);
    server.use(
      http.get(`${API}/workload`, () =>
        HttpResponse.json({
          items: [
            {
              team: { id: "team-1", name: "Roads North" },
              open: 3,
              pending_acceptance: 1,
              in_progress: 2,
              overdue: 0,
              members: [
                {
                  user: { id: "user-4", display_name: "Farah Field" },
                  open: 3,
                  in_progress: 2,
                },
              ],
            },
          ],
        }),
      ),
    );
    renderWithProviders(<WorkloadScreen />);

    const table = await screen.findByRole("region", {
      name: "Members of Roads North",
    });
    const cells = within(table)
      .getAllByRole("cell")
      .map((cell) => cell.textContent);
    expect(cells).toEqual(["Farah Field", "3", "2"]);
    expect(
      screen.getByText(/3 open · 1 waiting to be accepted · 2 in progress/),
    ).toBeInTheDocument();
  });
});

describe("ClosureSettings", () => {
  it("validates the limits before saving", async () => {
    signIn(["config:read", "config:manage"]);
    const saved = vi.fn();
    server.use(
      http.get(`${API}/admin/closure-config`, () =>
        HttpResponse.json({
          resolution_window_hours: 168,
          confirmations_required: 2,
        }),
      ),
      http.put(`${API}/admin/closure-config`, async ({ request }) => {
        const body = await request.json();
        saved(body);
        return HttpResponse.json(body);
      }),
    );
    const { user } = renderWithProviders(<ClosureSettings />);

    const confirmations = await screen.findByLabelText("Confirmations needed");
    await user.clear(confirmations);
    await user.type(confirmations, "11");
    await user.click(screen.getByRole("button", { name: /save/i }));
    expect(
      await screen.findByText("Enter a whole number from 1 to 10."),
    ).toBeInTheDocument();
    expect(saved).not.toHaveBeenCalled();

    await user.clear(confirmations);
    await user.type(confirmations, "3");
    await user.click(screen.getByRole("button", { name: /save/i }));
    await vi.waitFor(() =>
      expect(saved).toHaveBeenCalledWith({
        resolution_window_hours: 168,
        confirmations_required: 3,
      }),
    );
  });
});
