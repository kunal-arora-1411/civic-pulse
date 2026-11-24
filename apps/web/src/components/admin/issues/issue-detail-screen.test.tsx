import { act, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { session } from "@/lib/api";
import { makeAdmin, makeIssueDetail } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { IssueDetailScreen } from "./issue-detail-screen";

const navigation = vi.hoisted(() => ({
  replace: vi.fn(),
  search: "",
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(navigation.search),
}));
vi.mock("@/components/map/lazy-maps", () => ({
  PinMap: ({ label }: { label: string }) => <section aria-label={label} />,
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
  useRouter: () => ({ replace: navigation.replace, push: vi.fn() }),
}));

async function renderIssue(id: string) {
  const params = Promise.resolve({ id });
  await act(async () => {
    renderWithProviders(
      <Suspense fallback={null}>
        <IssueDetailScreen params={params} />
      </Suspense>,
    );
    await params;
  });
}

beforeEach(() => {
  navigation.replace.mockReset();
  navigation.search = "";
  session.setAuthenticated("token", makeAdmin({ permissions: ["issue:read"] }));
  server.use(http.get(`${API}/categories`, () => HttpResponse.json([])));
});
afterEach(() => session.reset());

describe("IssueDetailScreen and merged issues", () => {
  it("sends a merged issue on to the survivor, replacing the history entry", async () => {
    server.use(
      http.get(`${API}/issues/iss-old`, () =>
        HttpResponse.json({
          id: "iss-old",
          reference: "CP-26-000050",
          merged_into: { id: "iss-1", reference: "CP-26-000123" },
        }),
      ),
    );
    await renderIssue("iss-old");

    expect(
      await screen.findByText("CP-26-000050 was merged into CP-26-000123"),
    ).toBeInTheDocument();
    expect(navigation.replace).toHaveBeenCalledWith(
      "/admin/issues/iss-1?merged_from=CP-26-000050",
    );
    expect(
      screen.getByRole("link", { name: "Open CP-26-000123" }),
    ).toHaveAttribute("href", "/admin/issues/iss-1?merged_from=CP-26-000050");
  });

  it("redirects even when the merged issue comes back as a full detail", async () => {
    server.use(
      http.get(`${API}/issues/iss-old`, () =>
        HttpResponse.json({
          ...makeIssueDetail({ id: "iss-old", reference: "CP-26-000050" }),
          merged_into: { id: "iss-1", reference: "CP-26-000123" },
        }),
      ),
    );
    await renderIssue("iss-old");
    await screen.findByText("CP-26-000050 was merged into CP-26-000123");
    expect(navigation.replace).toHaveBeenCalledOnce();
  });

  it("tells the user on the survivor where they came from", async () => {
    navigation.search = "merged_from=CP-26-000050";
    server.use(
      http.get(`${API}/issues/iss-1`, () =>
        HttpResponse.json({ ...makeIssueDetail(), merged_into: null }),
      ),
    );
    await renderIssue("iss-1");
    expect(
      await screen.findByText(
        "CP-26-000050 was merged into this issue, so you've been brought here instead.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: "CP-26-000123" }),
    ).toBeInTheDocument();
    expect(navigation.replace).not.toHaveBeenCalled();
  });
});
