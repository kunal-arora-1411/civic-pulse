import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RequirePermission } from "@/components/auth/guards";
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
      "users",
      "audit",
    ]);
  });

  it("shows only the overview without admin permissions", () => {
    expect(visibleNavItems(operator).map((item) => item.key)).toEqual([
      "overview",
    ]);
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
    expect(links).toEqual(["Overview", "Users", "Audit log"]);
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

describe("RequirePermission", () => {
  it("shows a not-authorised state when the permission is missing", () => {
    session.setAuthenticated("token", operator);
    renderWithProviders(
      <RequirePermission permission="user:manage">
        <p>Secret staff list</p>
      </RequirePermission>,
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
      <RequirePermission permission="user:manage">
        <p>Staff list</p>
      </RequirePermission>,
    );
    expect(screen.getByText("Staff list")).toBeInTheDocument();
  });

  it("sends signed-out visitors to the login page", () => {
    session.clear();
    renderWithProviders(
      <RequirePermission permission="user:manage">
        <p>Staff list</p>
      </RequirePermission>,
    );
    expect(navigation.router.replace).toHaveBeenCalledWith(
      "/login?next=%2Fadmin%2Fusers",
    );
    expect(screen.queryByText("Staff list")).toBeNull();
  });
});
