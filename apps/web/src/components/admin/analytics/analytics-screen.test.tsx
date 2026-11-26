import { screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { RequireAdminAccess } from "@/components/auth/guards";
import { session } from "@/lib/api";
import { analyticsBodies, analyticsHandlers } from "@/test/analytics-handlers";
import { makeAdmin, makeTenant, makeUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { AnalyticsScreen } from "./analytics-screen";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock("@/i18n/navigation", () => ({
  usePathname: () => "/admin/analytics",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
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
// Leaflet needs a real layout engine; the map gets its own props checked.
const mapProps = vi.hoisted(() => ({ last: null as unknown }));
vi.mock("@/components/map/lazy-maps", () => ({
  HotspotMap: (props: { cells: unknown[]; label: string }) => {
    mapProps.last = props;
    return <div data-testid="hotspot-map">{props.cells.length} cells</div>;
  },
}));
// Handing a Blob to the browser is a DOM side effect with nothing to assert
// here beyond the name and body it receives.
const saveFileSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/download", () => ({ saveFile: saveFileSpy }));

beforeAll(() => {
  // Recharts sizes itself with ResizeObserver, which jsdom lacks.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

const page = (items: unknown[]) => ({
  items,
  total: items.length,
  limit: 100,
  offset: 0,
});

let requests: URL[] = [];

beforeEach(() => {
  requests = [];
  session.setAuthenticated(
    "token",
    makeAdmin({ permissions: ["analytics:read", "config:read"] }),
  );
  server.use(
    ...analyticsHandlers(requests),
    http.get(`${API}/tenants/current`, () => HttpResponse.json(makeTenant())),
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
afterEach(() => {
  session.reset();
  window.history.replaceState(null, "", "/");
});

describe("AnalyticsScreen", () => {
  it("shows the headline figures with their change on the previous period", async () => {
    renderWithProviders(<AnalyticsScreen />);

    const tiles = await screen.findByRole("list", { name: "Headline figures" });
    const reports = within(tiles).getByText("Reports").closest("li");
    expect(reports).toHaveTextContent("412");
    expect(reports).toHaveTextContent("+9%");
    // Faster resolution is better: 72 h against 96 h before.
    const resolve = within(tiles)
      .getByText("Median time to resolve")
      .closest("li");
    expect(resolve).toHaveTextContent("3 d");
    expect(resolve).toHaveTextContent("-25%, better");
    // Ratios move in percentage points.
    const dupes = within(tiles).getByText("Duplicate rate").closest("li");
    expect(dupes).toHaveTextContent("+4 pts");
    const review = within(tiles).getByText("Sent to review").closest("li");
    expect(review).toHaveTextContent("No comparison");
  });

  it("sends the filters in the URL to every endpoint", async () => {
    window.history.replaceState(
      null,
      "",
      "/admin/analytics?range=custom&from=2026-10-01&to=2026-10-31&ward=w1&status=resolved",
    );
    renderWithProviders(<AnalyticsScreen />);

    await waitFor(() => expect(requests.length).toBeGreaterThanOrEqual(9));
    const paths = new Set(requests.map((url) => url.pathname.split("/").pop()));
    expect(paths).toEqual(
      new Set([
        "overview",
        "trend",
        "by-status",
        "by-category",
        "by-ward",
        "resolution-times",
        "matching-quality",
        "hotspots",
        "activity",
      ]),
    );
    for (const url of requests) {
      expect(url.searchParams.get("from")).toBe("2026-10-01");
      expect(url.searchParams.get("to")).toBe("2026-10-31");
      expect(url.searchParams.get("ward_id")).toBe("w1");
      expect(url.searchParams.getAll("status")).toEqual(["resolved"]);
    }
    expect(
      requests
        .find((url) => url.pathname.endsWith("/trend"))
        ?.searchParams.get("interval"),
    ).toBe("day");
    expect(await screen.findByLabelText("Period")).toHaveValue("custom");
  });

  it("writes filter changes and the trend interval to the URL", async () => {
    const { user } = renderWithProviders(<AnalyticsScreen />);
    await screen.findByRole("list", { name: "Headline figures" });

    await user.selectOptions(screen.getByLabelText("Period"), "90d");
    expect(window.location.search).toBe("?range=90d");

    await user.click(screen.getByRole("button", { name: "Weekly" }));
    expect(window.location.search).toBe("?range=90d&interval=week");
  });

  it("offers every chart as a table", async () => {
    const { user } = renderWithProviders(<AnalyticsScreen />);

    const toggle = await screen.findByRole("button", {
      name: "View as table: Ward ranking",
    });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    const table = screen.getByRole("table", { name: "Ward ranking" });
    expect(
      within(table).getByRole("rowheader", { name: "Ward 1" }),
    ).toBeInTheDocument();
    expect(within(table).getByText("Outside any ward")).toBeInTheDocument();
    expect(within(table).getByText("2.5 d")).toBeInTheDocument();

    // The status table keeps the exact statuses the chart folds together.
    await user.click(
      screen.getByRole("button", { name: "View as table: Where issues stand" }),
    );
    const statuses = screen.getByRole("table", { name: "Where issues stand" });
    expect(within(statuses).getByText("Closed")).toBeInTheDocument();
    expect(within(statuses).getByText("In progress")).toBeInTheDocument();

    expect(
      screen.getAllByRole("button", { name: /^View as (table|chart):/ }),
    ).toHaveLength(8);
  });

  it("describes each chart and draws the hotspots", async () => {
    renderWithProviders(<AnalyticsScreen />);

    const trend = await screen.findByRole("figure", {
      name: "Reports and resolutions over time",
    });
    await waitFor(() =>
      expect(trend).toHaveAccessibleDescription(
        "36 reports, 27 new issues and 18 resolutions in the period.",
      ),
    );
    expect(
      screen.getByRole("figure", { name: "Time to resolve" }),
    ).toHaveAccessibleDescription(
      "20 issues resolved; median 2.5 d, 90th percentile 8.3 d.",
    );
    expect(
      screen.getByRole("figure", { name: "When citizens report" }),
    ).toHaveAccessibleDescription(
      "The busiest hour is Monday at 08:00 with 12 reports.",
    );
    expect(await screen.findByTestId("hotspot-map")).toHaveTextContent(
      "1 cells",
    );
    expect(mapProps.last).toMatchObject({
      cells: [
        { cell: "8861892e0bfffff", issues: 17, label: "17 issues, 6 open" },
      ],
    });
    // The donut's legend carries each stage's count and share.
    expect(screen.getByText("20 (50%)")).toBeInTheDocument();
  });

  it("shows an error on the chart that failed, with a retry, and keeps the rest", async () => {
    let fail = true;
    server.use(
      http.get(`${API}/analytics/by-ward`, () =>
        fail
          ? HttpResponse.json(
              { error: { code: "internal_error", message: "" } },
              { status: 500 },
            )
          : HttpResponse.json(analyticsBodies.byWard),
      ),
    );
    const { user } = renderWithProviders(<AnalyticsScreen />);

    const card = (
      await screen.findByRole("heading", { name: "Ward ranking" })
    ).closest("section") as HTMLElement;
    expect(
      await within(card).findByText("This chart couldn't load."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("list", { name: "Headline figures" }),
    ).toBeInTheDocument();

    fail = false;
    await user.click(within(card).getByRole("button", { name: "Try again" }));
    expect(
      await within(card).findByRole("figure", { name: "Ward ranking" }),
    ).toBeInTheDocument();
  });

  it("says so when there is nothing to show", async () => {
    server.use(
      http.get(`${API}/analytics/by-category`, () =>
        HttpResponse.json({ ...analyticsBodies.byCategory, items: [] }),
      ),
    );
    renderWithProviders(<AnalyticsScreen />);

    const card = (
      await screen.findByRole("heading", { name: "Issues by category" })
    ).closest("section") as HTMLElement;
    expect(
      await within(card).findByText("No data for these filters."),
    ).toBeInTheDocument();
    expect(
      within(card).queryByRole("button", { name: /View as table/ }),
    ).not.toBeInTheDocument();
  });

  it("is not shown to staff without analytics:read", async () => {
    session.setAuthenticated(
      "token",
      makeUser({
        is_staff: true,
        roles: [
          { role: "operator", department_id: null, jurisdiction_id: null },
        ],
        permissions: ["issue:read"],
      }),
    );
    renderWithProviders(
      <RequireAdminAccess permission="analytics:read">
        <AnalyticsScreen />
      </RequireAdminAccess>,
    );

    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Analytics" }),
      ).not.toBeInTheDocument(),
    );
    expect(requests).toHaveLength(0);
  });

  it("downloads the filtered issues as the file the server names", async () => {
    window.history.replaceState(
      null,
      "",
      "/admin/analytics?range=custom&from=2026-10-01&to=2026-10-31&ward=w1",
    );
    saveFileSpy.mockReset();
    const exported: URL[] = [];
    server.use(
      http.get(`${API}/analytics/export`, ({ request }) => {
        exported.push(new URL(request.url));
        return new HttpResponse("reference,status\nCP-1,resolved\n", {
          headers: {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition":
              'attachment; filename="issues-2026-10-01-to-2026-10-31.csv"',
            "X-Export-Rows": "2",
            "X-Export-Truncated": "false",
          },
        });
      }),
    );
    const { user } = renderWithProviders(<AnalyticsScreen />);

    await user.click(
      await screen.findByRole("button", { name: "Download CSV" }),
    );

    await waitFor(() => expect(saveFileSpy).toHaveBeenCalledTimes(1));
    const [blob, filename] = saveFileSpy.mock.calls[0];
    expect(filename).toBe("issues-2026-10-01-to-2026-10-31.csv");
    expect(await (blob as Blob).text()).toContain("CP-1,resolved");
    // The file covers exactly what the figures cover.
    expect(exported).toHaveLength(1);
    expect(exported[0].searchParams.get("from")).toBe("2026-10-01");
    expect(exported[0].searchParams.get("to")).toBe("2026-10-31");
    expect(exported[0].searchParams.get("ward_id")).toBe("w1");
    expect(await screen.findByText("2 issues downloaded")).toBeInTheDocument();
  });

  it("says when the file was capped instead of passing it off as complete", async () => {
    saveFileSpy.mockReset();
    server.use(
      http.get(
        `${API}/analytics/export`,
        () =>
          new HttpResponse("reference\n", {
            headers: {
              "Content-Type": "text/csv; charset=utf-8",
              "X-Export-Rows": "20000",
              "X-Export-Truncated": "true",
            },
          }),
      ),
    );
    const { user } = renderWithProviders(<AnalyticsScreen />);

    await user.click(
      await screen.findByRole("button", { name: "Download CSV" }),
    );

    expect(
      await screen.findByText(/Partial file: the first 20,?000 issues/),
    ).toBeInTheDocument();
    // Without a Content-Disposition the file still gets a usable name.
    expect(saveFileSpy.mock.calls[0][1]).toBe("issues.csv");
  });

  it("explains a failed export instead of downloading nothing", async () => {
    saveFileSpy.mockReset();
    server.use(
      http.get(`${API}/analytics/export`, () =>
        HttpResponse.json(
          {
            error: {
              code: "forbidden",
              message: "Missing permission.",
              request_id: "r1",
            },
          },
          { status: 403 },
        ),
      ),
    );
    const { user } = renderWithProviders(<AnalyticsScreen />);

    await user.click(
      await screen.findByRole("button", { name: "Download CSV" }),
    );

    expect(
      await screen.findByText("Couldn't download the file"),
    ).toBeInTheDocument();
    expect(saveFileSpy).not.toHaveBeenCalled();
  });
});
