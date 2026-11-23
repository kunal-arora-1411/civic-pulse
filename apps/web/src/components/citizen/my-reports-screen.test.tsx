import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { MyReportsScreen } from "./my-reports-screen";

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

const page = (items: unknown[]) => ({
  items,
  total: items.length,
  limit: 20,
  offset: 0,
});

describe("MyReportsScreen", () => {
  it("lists reports with a status that has text and an icon", async () => {
    server.use(
      http.get(`${API}/users/me/reports`, () =>
        HttpResponse.json(
          page([
            {
              id: "rep-1",
              reference: "R-26-000123",
              created_at: "2026-11-24T08:15:00+05:30",
              category: {
                id: "c",
                code: "pothole",
                name_i18n: { en: "Pothole / road damage" },
                icon: "construction",
              },
              thumb_url: null,
              address_text: "MG Road",
              issue: { reference: "CP-26-000123", status: "under_review" },
            },
          ]),
        ),
      ),
    );
    renderWithProviders(<MyReportsScreen />);

    const link = await screen.findByRole("link", { name: /pothole/i });
    expect(link).toHaveAttribute("href", "/reports/rep-1");
    expect(link).toHaveTextContent("R-26-000123");
    expect(link).toHaveTextContent("Under review");
    expect(link).toHaveTextContent("MG Road");
    expect(link.querySelector("svg")).not.toBeNull();
  });

  it("invites a first report when there are none", async () => {
    server.use(
      http.get(`${API}/users/me/reports`, () => HttpResponse.json(page([]))),
    );
    renderWithProviders(<MyReportsScreen />);

    expect(
      await screen.findByText("You haven't reported anything yet"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /report your first issue/i }),
    ).toHaveAttribute("href", "/report");
  });
});
