import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { session } from "@/lib/api";
import { makeAdmin, makeIssue } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { IssuesScreen } from "./issues-screen";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
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
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const page = (items: unknown[]) => ({
  items,
  total: items.length,
  limit: 25,
  offset: 0,
});

beforeEach(() => {
  session.setAuthenticated(
    "token",
    makeAdmin({ permissions: ["issue:read", "config:read"] }),
  );
  server.use(
    http.get(`${API}/admin/categories`, () => HttpResponse.json(page([]))),
    http.get(`${API}/admin/jurisdictions`, () =>
      HttpResponse.json(
        page([
          {
            id: "w3",
            parent_id: null,
            kind: "ward",
            name: "Ward 3",
            code: "W03",
          },
        ]),
      ),
    ),
  );
});
afterEach(() => {
  session.reset();
  window.history.replaceState(null, "", "/");
});

describe("IssuesScreen", () => {
  it("loads the view described by the URL and links rows to the detail page", async () => {
    window.history.replaceState(
      null,
      "",
      "/admin/issues?status=reported&status=under_review&ward=w3&sort=-report_count&page=2",
    );
    let requested: URL | undefined;
    server.use(
      http.get(`${API}/issues`, ({ request }) => {
        requested = new URL(request.url);
        return HttpResponse.json({
          ...page([makeIssue({ report_count: 4 })]),
          total: 26,
          offset: 25,
        });
      }),
    );

    renderWithProviders(<IssuesScreen />);

    const link = await screen.findByRole("link", { name: "CP-26-000123" });
    expect(link).toHaveAttribute("href", "/admin/issues/iss-1");
    expect(requested?.searchParams.getAll("status")).toEqual([
      "reported",
      "under_review",
    ]);
    expect(requested?.searchParams.getAll("ward_id")).toEqual(["w3"]);
    expect(requested?.searchParams.get("sort")).toBe("-report_count");
    expect(requested?.searchParams.get("offset")).toBe("25");
    expect(
      screen.getByRole("columnheader", { name: /reports/i }),
    ).toHaveAttribute("aria-sort", "descending");
  });

  it("writes sort changes to the URL and resets to page 1", async () => {
    window.history.replaceState(
      null,
      "",
      "/admin/issues?status=verified&page=3",
    );
    server.use(
      http.get(`${API}/issues`, () => HttpResponse.json(page([makeIssue()]))),
    );
    const { user } = renderWithProviders(<IssuesScreen />);
    await screen.findByRole("link", { name: "CP-26-000123" });

    await user.click(screen.getByRole("button", { name: /^age/i }));

    // Newest first is the default, so the first click sorts oldest first.
    expect(window.location.search).toBe("?status=verified&sort=created_at");
  });
});
