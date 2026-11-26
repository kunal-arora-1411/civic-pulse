import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { PUBLIC } from "@/test/community";
import { server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { PublicAnnouncements } from "./announcements";

describe("PublicAnnouncements", () => {
  it("shows the notices running now, without signing in", async () => {
    let authorization: string | null = "unset";
    server.use(
      http.get(`${PUBLIC}/announcements`, ({ request }) => {
        authorization = request.headers.get("Authorization");
        return HttpResponse.json([
          {
            id: "a1",
            kind: "outage",
            title_i18n: { en: "Water outage" },
            body_i18n: { en: "No supply 10am to 2pm." },
            ward: { id: "w1", code: "W01", name: "Ward 1" },
            category: null,
            starts_at: "2026-11-27T04:30:00Z",
            ends_at: "2026-11-27T08:30:00Z",
          },
        ]);
      }),
    );
    renderWithProviders(<PublicAnnouncements />);

    expect(
      await screen.findByRole("heading", { name: "Water outage" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Service outage · Ward 1/)).toBeInTheDocument();
    expect(screen.getByText(/Until .*2:00\s?PM/)).toBeInTheDocument();
    expect(authorization).toBeNull();
  });

  it("renders nothing when there are no notices", async () => {
    let asked = false;
    server.use(
      http.get(`${PUBLIC}/announcements`, () => {
        asked = true;
        return HttpResponse.json([]);
      }),
    );
    renderWithProviders(<PublicAnnouncements />);
    await vi.waitFor(() => expect(asked).toBe(true));
    expect(
      screen.queryByRole("heading", { name: "Service announcements" }),
    ).not.toBeInTheDocument();
  });
});
