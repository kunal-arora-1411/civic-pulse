import { screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { type AuditEvent, session } from "@/lib/api";
import { makeAdmin } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { AuditScreen } from "./audit-screen";
import { changedKeys } from "./json-diff";

const rolesChanged: AuditEvent = {
  id: 41,
  occurred_at: "2026-11-20T06:15:00Z",
  actor: { id: "u-admin", display_name: "Meera Admin" },
  action: "user.roles_changed",
  entity_type: "user",
  entity_id: "u-2",
  before: { roles: ["operator"], is_active: true },
  after: { roles: ["operator", "supervisor"], is_active: true },
  request_id: "req-abc",
};

let requests: URL[] = [];

beforeEach(() => {
  requests = [];
  session.setAuthenticated("token", makeAdmin());
  server.use(
    http.get(`${API}/admin/audit-events`, ({ request }) => {
      const url = new URL(request.url);
      requests.push(url);
      const action = url.searchParams.get("action");
      const items =
        action && action !== rolesChanged.action ? [] : [rolesChanged];
      return HttpResponse.json({
        items,
        total: items.length,
        limit: 25,
        offset: 0,
      });
    }),
  );
});
afterEach(() => session.reset());

describe("AuditScreen", () => {
  it("expands an event to show before/after JSON and what changed", async () => {
    const { user } = renderWithProviders(<AuditScreen />);

    expect(await screen.findByText("user.roles_changed")).toBeInTheDocument();
    expect(screen.getByText("Meera Admin")).toBeInTheDocument();
    // Shown in IST: 06:15 UTC is 11:45 IST.
    expect(screen.getByText(/11:45/)).toBeInTheDocument();

    const toggle = screen.getByRole("button", {
      name: /show details for user\.roles_changed/i,
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    const details = document.getElementById(
      toggle.getAttribute("aria-controls") ?? "",
    );
    expect(details).not.toBeNull();
    const panel = within(details as HTMLElement);
    expect(panel.getByText("roles")).toBeInTheDocument();
    expect(panel.getByText("Before").nextElementSibling).toHaveTextContent(
      /"operator"\s*\]/,
    );
    expect(panel.getByText("After").nextElementSibling).toHaveTextContent(
      /"supervisor"/,
    );
  });

  it("filters by action and shows an empty state", async () => {
    const { user } = renderWithProviders(<AuditScreen />);
    await screen.findByText("user.roles_changed");

    await user.type(screen.getByLabelText("Action"), "user.created");

    expect(
      await screen.findByText("No events match these filters"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(requests.at(-1)?.searchParams.get("action")).toBe("user.created"),
    );
  });

  it("sends date filters as IST day boundaries", async () => {
    const { user } = renderWithProviders(<AuditScreen />);
    await screen.findByText("user.roles_changed");

    await user.type(screen.getByLabelText("From"), "2026-11-20");

    await waitFor(() =>
      expect(requests.at(-1)?.searchParams.get("from")).toBe(
        "2026-11-19T18:30:00.000Z",
      ),
    );
  });
});

describe("changedKeys", () => {
  it("lists top-level keys whose values differ", () => {
    expect(
      changedKeys({ a: 1, b: [1], c: "x" }, { a: 1, b: [1, 2], d: true }),
    ).toEqual(["b", "c", "d"]);
  });

  it("treats null sides as empty objects", () => {
    expect(changedKeys(null, { is_active: false })).toEqual(["is_active"]);
  });
});
