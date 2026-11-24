import { screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { makeScorecard, PUBLIC } from "@/test/community";
import { server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { ScorecardScreen } from "./scorecard";

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

describe("ward scorecard", () => {
  it("shows open, resolved and the median days for each ward", async () => {
    server.use(
      http.get(`${PUBLIC}/scorecard`, () => HttpResponse.json(makeScorecard())),
    );
    renderWithProviders(<ScorecardScreen />);

    const first = (
      await screen.findByRole("heading", { name: "Ward 1 (synthetic)" })
    ).closest("li") as HTMLElement;
    expect(first).toHaveTextContent("Open: 4");
    expect(first).toHaveTextContent("Resolved: 6");
    expect(within(first).getByText("3.5 days")).toBeInTheDocument();

    const second = screen
      .getByRole("heading", { name: "Ward 3 (synthetic)" })
      .closest("li") as HTMLElement;
    expect(second).toHaveTextContent("Nothing fixed yet");
  });

  it("offers a retry when it can't load", async () => {
    server.use(
      http.get(`${PUBLIC}/scorecard`, () =>
        HttpResponse.json(
          { error: { code: "internal_error", message: "Boom" } },
          { status: 500 },
        ),
      ),
    );
    renderWithProviders(<ScorecardScreen />);
    expect(
      await screen.findByText("We couldn't load the scorecard"),
    ).toBeInTheDocument();
  });
});
