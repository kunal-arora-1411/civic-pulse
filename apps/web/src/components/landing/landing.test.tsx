import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { session } from "@/lib/api";
import { makeAdmin, makeUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import hi from "../../../messages/hi.json";
import { Bento } from "./bento";
import { LandingFooter } from "./footer";
import { CtaBanner, ForCities } from "./for-cities";
import { LandingHeader } from "./header";
import { Hero } from "./hero";
import { LiveMap } from "./live-map";
import { RecentReportsStrip } from "./session-parts";

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
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));

function Landing() {
  return (
    <>
      <LandingHeader />
      <main>
        <Hero />
        <RecentReportsStrip />
        <LiveMap />
        <Bento />
        <ForCities />
        <CtaBanner />
      </main>
      <LandingFooter />
    </>
  );
}

const recentReports = {
  items: [
    {
      id: "rep-7",
      reference: "R-26-000777",
      created_at: "2026-11-24T08:15:00+05:30",
      category: {
        id: "c",
        code: "streetlight",
        name_i18n: { en: "Streetlight not working" },
        icon: "lightbulb",
      },
      thumb_url: null,
      address_text: "Park Road",
      issue: { reference: "CP-26-000777", status: "reported" },
    },
  ],
  total: 1,
  limit: 3,
  offset: 0,
};

afterEach(() => session.reset());

describe("Landing page", () => {
  it("has one H1 and sends every report entry point to /report", () => {
    renderWithProviders(<Landing />);

    const headings = screen.getAllByRole("heading", { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]).toHaveTextContent("What needs fixing on your street?");

    expect(
      screen.getByRole("link", { name: "Start a report" }),
    ).toHaveAttribute("href", "/report");
    const rail = screen.getByRole("navigation", { name: "Report by category" });
    const tiles = within(rail).getAllByRole("link");
    expect(tiles.map((tile) => tile.textContent)).toEqual([
      "Pothole",
      "Streetlight",
      "Garbage",
      "Blocked drain",
      "Water leak",
      "Fallen tree",
    ]);
    for (const tile of tiles) expect(tile).toHaveAttribute("href", "/report");

    const header = screen.getByRole("banner");
    expect(
      within(header).getByRole("link", { name: "Report an issue" }),
    ).toHaveAttribute("href", "/report");
  });

  it("shows final figures and labels them as illustrative without motion", () => {
    // jsdom has no matchMedia, which the page treats as reduced motion.
    renderWithProviders(<Landing />);
    const stats = screen.getByLabelText("CivicPulse in numbers");
    expect(stats).toHaveTextContent("9,312");
    expect(stats).toHaveTextContent("3.2 days");
    expect(stats).toHaveTextContent("42");
    expect(stats).toHaveTextContent("38%");
    expect(screen.getByText(/Illustrative pilot figures/)).toBeInTheDocument();
  });

  it("offers sign-in to visitors and shows no personal reports", () => {
    session.clear();
    renderWithProviders(<Landing />);

    expect(
      within(screen.getByRole("banner")).getByRole("link", { name: "Sign in" }),
    ).toHaveAttribute("href", "/login");
    expect(
      screen.queryByRole("heading", { name: /welcome back/i }),
    ).not.toBeInTheDocument();
  });

  it("gives signed-in citizens their account menu and latest reports", async () => {
    session.setAuthenticated("token", makeUser());
    server.use(
      http.get(`${API}/users/me/reports`, () =>
        HttpResponse.json(recentReports),
      ),
    );
    renderWithProviders(<Landing />);

    const header = screen.getByRole("banner");
    expect(
      within(header).getByRole("button", { name: /asha/i }),
    ).toBeInTheDocument();
    expect(
      within(header).queryByRole("link", { name: "Sign in" }),
    ).not.toBeInTheDocument();

    expect(
      screen.getByRole("heading", { name: /welcome back/i }),
    ).toBeInTheDocument();
    expect(
      await within(
        screen.getByRole("region", { name: /welcome back/i }),
      ).findByRole("link", { name: /streetlight/i }),
    ).toHaveAttribute("href", "/reports/rep-7");
    expect(
      screen.queryByRole("link", { name: "Go to the admin console" }),
    ).not.toBeInTheDocument();
  });

  it("adds the console shortcut for staff", async () => {
    session.setAuthenticated("token", makeAdmin());
    server.use(
      http.get(`${API}/users/me/reports`, () =>
        HttpResponse.json({ ...recentReports, items: [], total: 0 }),
      ),
    );
    renderWithProviders(<Landing />);

    expect(
      screen.getByRole("link", { name: "Go to the admin console" }),
    ).toHaveAttribute("href", "/admin");
    expect(
      await screen.findByText(/haven't reported anything yet/),
    ).toBeInTheDocument();
  });

  it("switches console views with the tabs, including by keyboard", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Landing />);

    const tablist = screen.getByRole("tablist", { name: "Console views" });
    const queue = within(tablist).getByRole("tab", { name: "Queue" });
    expect(queue).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("img", { name: "Illustration of the staff console" }),
    ).toBeVisible();

    await user.click(within(tablist).getByRole("tab", { name: "Audit log" }));
    expect(screen.getByText("Assigned to Crew 7")).toBeVisible();
    expect(
      screen.queryByRole("img", { name: "Illustration of the staff console" }),
    ).not.toBeInTheDocument();

    await user.keyboard("{ArrowRight}");
    const field = within(tablist).getByRole("tab", { name: "Field app" });
    expect(field).toHaveAttribute("aria-selected", "true");
    expect(field).toHaveFocus();
    expect(screen.getByText("Today's jobs · Crew 7")).toBeVisible();
  });

  it("renders in Hindi", async () => {
    const queryClient = new QueryClient();
    await act(async () => {
      render(
        <NextIntlClientProvider
          locale="hi"
          messages={hi}
          timeZone="Asia/Kolkata"
        >
          <QueryClientProvider client={queryClient}>
            <Landing />
          </QueryClientProvider>
        </NextIntlClientProvider>,
      );
    });

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "आपकी गली में क्या ठीक होना है?",
    );
    expect(
      screen.getByRole("link", { name: "शिकायत दर्ज करना शुरू करें" }),
    ).toHaveAttribute("href", "/report");
  });
});
