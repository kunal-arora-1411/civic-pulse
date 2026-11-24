import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RequireAdminAccess } from "@/components/auth/guards";
import { session } from "@/lib/api";
import { makeAdmin, makeUser } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { AdminNav } from "./admin-nav";
import { visibleNavItems } from "./nav-items";

const navigation = vi.hoisted(() => ({
  pathname: "/admin/users",
  router: { replace: vi.fn(), push: vi.fn() },
}));
vi.mock("@/i18n/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => navigation.router,
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

const operator = makeUser({
  is_staff: true,
  roles: [{ role: "operator", department_id: null, jurisdiction_id: null }],
  permissions: ["issue:triage"],
});
const auditor = makeUser({
  is_staff: true,
  roles: [
    { role: "supervisor", department_id: "roads", jurisdiction_id: null },
  ],
  permissions: ["audit:read"],
});

describe("visibleNavItems", () => {
  it("shows every section to a municipal admin", () => {
    expect(visibleNavItems(makeAdmin()).map((item) => item.key)).toEqual([
      "overview",
      "categories",
      "matching",
      "priority",
      "ai",
      "users",
      "audit",
    ]);
  });

  it("shows the review queue, and no admin sections, to a triage-only operator", () => {
    expect(visibleNavItems(operator).map((item) => item.key)).toEqual([
      "overview",
      "review",
    ]);
  });

  it("shows the work queue to staff with issue:read", () => {
    const reader = makeUser({
      is_staff: true,
      roles: [{ role: "operator", department_id: null, jurisdiction_id: null }],
      permissions: ["issue:read"],
    });
    expect(visibleNavItems(reader).map((item) => item.key)).toContain("issues");
  });

  it("filters each entry by its own permission", () => {
    expect(visibleNavItems(auditor).map((item) => item.key)).toEqual([
      "overview",
      "audit",
    ]);
  });
});

describe("AdminNav", () => {
  it("renders only permitted links and marks the current page", () => {
    renderWithProviders(<AdminNav user={makeAdmin()} />);

    const nav = screen.getByRole("navigation", { name: "Admin sections" });
    const links = Array.from(nav.querySelectorAll("a")).map(
      (a) => a.textContent,
    );
    expect(links).toEqual([
      "Overview",
      "Categories",
      "Matching",
      "Priority rules",
      "AI models",
      "Users",
      "Audit log",
    ]);
    expect(screen.getByRole("link", { name: "Users" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Overview" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("hides the users link from staff without user:manage", () => {
    renderWithProviders(<AdminNav user={auditor} />);

    expect(screen.queryByRole("link", { name: "Users" })).toBeNull();
    expect(screen.getByRole("link", { name: "Audit log" })).toBeInTheDocument();
  });
});

describe("RequireAdminAccess", () => {
  it("shows a not-authorised state when the permission is missing", () => {
    session.setAuthenticated("token", operator);
    renderWithProviders(
      <RequireAdminAccess permission="user:manage">
        <p>Secret staff list</p>
      </RequireAdminAccess>,
    );

    expect(
      screen.getByRole("heading", {
        name: "You don't have access to this page",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Secret staff list")).toBeNull();
  });

  it("renders the page when the permission is present", () => {
    session.setAuthenticated("token", makeAdmin());
    renderWithProviders(
      <RequireAdminAccess permission="user:manage">
        <p>Staff list</p>
      </RequireAdminAccess>,
    );
    expect(screen.getByText("Staff list")).toBeInTheDocument();
  });

  it("sends signed-out visitors to the login page", () => {
    window.history.replaceState(null, "", "/admin/users");
    session.clear();
    renderWithProviders(
      <RequireAdminAccess permission="user:manage">
        <p>Staff list</p>
      </RequireAdminAccess>,
    );
    expect(navigation.router.replace).toHaveBeenCalledWith(
      "/login?next=%2Fadmin%2Fusers",
    );
    expect(screen.queryByText("Staff list")).toBeNull();
  });
});
