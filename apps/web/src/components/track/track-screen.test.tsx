import { screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makePublicIssue, PUBLIC, publicHandlers } from "@/test/community";
import { makeCategory, makeTenant } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { TrackScreen } from "./track-screen";

const push = vi.fn();

vi.mock("@/components/map/lazy-maps", () => ({
  IssuesMap: ({
    features,
    label,
    markerLabel,
    onSelect,
  }: {
    features: {
      properties: { id: string; reference: string; status: string };
    }[];
    label: string;
    markerLabel: (p: unknown) => string;
    onSelect: (id: string) => void;
  }) => (
    <section aria-label={label}>
      {features.map((f) => (
        <button
          key={f.properties.id}
          type="button"
          onClick={() => onSelect(f.properties.id)}
        >
          {markerLabel(f.properties)}
        </button>
      ))}
    </section>
  ),
  MapSkeleton: () => null,
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
  useRouter: () => ({ push }),
}));

const open = makePublicIssue();
const fixed = makePublicIssue({
  id: "iss-2",
  reference: "CP-26-000124",
  status: "resolved",
  support_count: 0,
  report_count: 1,
});

beforeEach(() => {
  push.mockReset();
  server.use(
    http.get(`${API}/tenants/current`, () => HttpResponse.json(makeTenant())),
    http.get(`${API}/categories`, () =>
      HttpResponse.json([makeCategory({ id: "cat-pothole" })]),
    ),
    ...publicHandlers([open, fixed]),
  );
});

describe("public tracker", () => {
  it("lists issues and maps them, without signing in", async () => {
    const { user } = renderWithProviders(<TrackScreen />);

    expect(
      await screen.findByRole("heading", { name: "2 issues" }),
    ).toBeInTheDocument();
    const list = screen.getByRole("list");
    const links = within(list).getAllByRole("link");
    expect(links[0]).toHaveAttribute("href", "/track/iss-1");
    expect(links[0]).toHaveTextContent("CP-26-000123");
    expect(links[0]).toHaveTextContent("5 supporters");
    expect(links[0]).toHaveTextContent("Ward 3 (synthetic)");

    const map = await screen.findByRole("region", {
      name: "Map of reported issues, coloured by status",
    });
    await user.click(
      within(map).getByRole("button", { name: "CP-26-000124, Resolved" }),
    );
    expect(push).toHaveBeenCalledWith("/track/iss-2");
  });

  it("sends the filters and the sort to the API", async () => {
    const seen: URLSearchParams[] = [];
    server.use(
      http.get(`${PUBLIC}/issues`, ({ request }) => {
        const params = new URL(request.url).searchParams;
        seen.push(params);
        const items = params.getAll("status").includes("resolved")
          ? [fixed]
          : [open, fixed];
        return HttpResponse.json({
          items,
          total: items.length,
          limit: 20,
          offset: 0,
        });
      }),
    );
    const { user } = renderWithProviders(<TrackScreen />);
    await screen.findByRole("heading", { name: "2 issues" });

    await user.selectOptions(screen.getByLabelText("Status"), "resolved");
    expect(
      await screen.findByRole("heading", { name: "1 issue" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByLabelText("Ward")).toHaveTextContent(
        "Ward 1 (synthetic)",
      ),
    );
    await user.selectOptions(screen.getByLabelText("Ward"), "ward-1");
    await user.selectOptions(
      screen.getByLabelText("Sort by"),
      "-support_count",
    );

    await waitFor(() => {
      const last = seen.at(-1);
      expect(last?.getAll("status")).toEqual(["resolved"]);
      expect(last?.get("ward_id")).toBe("ward-1");
      expect(last?.get("sort")).toBe("-support_count");
    });

    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => {
      const last = seen.at(-1);
      expect(last?.getAll("status")).toEqual([]);
      expect(last?.get("sort")).toBe("-support_count");
    });
  });

  it("says when nothing matches, and offers a retry on errors", async () => {
    server.use(
      http.get(`${PUBLIC}/issues`, () =>
        HttpResponse.json(
          { error: { code: "internal_error", message: "Boom" } },
          { status: 500 },
        ),
      ),
    );
    renderWithProviders(<TrackScreen />);
    expect(
      await screen.findByText("We couldn't load the issues"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });
});
