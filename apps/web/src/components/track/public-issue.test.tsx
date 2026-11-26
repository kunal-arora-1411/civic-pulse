import { act, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { Suspense } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { session } from "@/lib/api";
import { makePublicDetail, PUBLIC } from "@/test/community";
import { server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { PublicIssue } from "./public-issue";

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
}));

afterEach(() => session.reset());

async function renderIssue(id = "iss-1") {
  const params = Promise.resolve({ id });
  await act(async () => {
    renderWithProviders(
      <Suspense fallback={null}>
        <PublicIssue params={params} />
      </Suspense>,
    );
    await params;
  });
}

describe("public issue page", () => {
  it("shows the timeline, before and after photos and a sign-in prompt", async () => {
    session.clear();
    let auth: string | null = "unset";
    server.use(
      http.get(`${PUBLIC}/issues/iss-1`, ({ request }) => {
        auth = request.headers.get("Authorization");
        return HttpResponse.json(
          makePublicDetail({
            status: "resolved",
            after_photos: [
              {
                thumb_url: "http://storage.test/after-thumb.webp",
                display_url: "http://storage.test/after.webp",
              },
            ],
          }),
        );
      }),
    );
    await renderIssue();

    expect(
      await screen.findByRole("heading", { name: "Pothole", level: 1 }),
    ).toBeInTheDocument();
    expect(auth).toBeNull();
    expect(screen.getByRole("heading", { name: "Before" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "After" })).toBeVisible();
    expect(screen.getAllByRole("button", { name: /open photo/i })).toHaveLength(
      2,
    );
    expect(screen.getByText(/Shown to within about 175 m/)).toBeInTheDocument();
    expect(screen.getByText("5 people face this")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Sign in to say you face this too" }),
    ).toHaveAttribute("href", "/login?next=%2Ftrack%2Fiss-1");
  });

  it("links a merged issue to the one it joined", async () => {
    session.clear();
    server.use(
      http.get(`${PUBLIC}/issues/iss-1`, () =>
        HttpResponse.json(
          makePublicDetail({
            merged_into: "CP-26-000090",
            merged_into_id: "iss-90",
          }),
        ),
      ),
    );
    await renderIssue();
    expect(
      await screen.findByRole("link", { name: "CP-26-000090" }),
    ).toHaveAttribute("href", "/track/iss-90");
    // Support goes to the surviving issue, not this one.
    expect(
      screen.queryByRole("link", { name: /sign in to say/i }),
    ).not.toBeInTheDocument();
  });

  it("says when the issue isn't public", async () => {
    server.use(
      http.get(`${PUBLIC}/issues/nope`, () =>
        HttpResponse.json(
          { error: { code: "not_found", message: "Missing" } },
          { status: 404 },
        ),
      ),
    );
    await renderIssue("nope");
    expect(await screen.findByText("Issue not found")).toBeInTheDocument();
  });
});
