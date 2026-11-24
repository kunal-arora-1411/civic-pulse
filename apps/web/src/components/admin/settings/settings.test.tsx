import { fireEvent, screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { session } from "@/lib/api";
import {
  DEFAULT_MATCHING_CONFIG,
  DEFAULT_PRIORITY_CONFIG,
} from "@/lib/settings/config";
import { makeAdmin } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { AiScreen } from "./ai-screen";
import { MatchingSettings } from "./matching-settings";
import { PrioritySettings } from "./priority-settings";

afterEach(() => session.reset());

function signIn(manage = true) {
  session.setAuthenticated(
    "token",
    makeAdmin({
      permissions: manage ? ["config:read", "config:manage"] : ["config:read"],
    }),
  );
}

describe("MatchingSettings", () => {
  it("validates each threshold next to its field and won't save until fixed", async () => {
    signIn();
    const saved: unknown[] = [];
    server.use(
      http.get(`${API}/admin/matching-config`, () =>
        HttpResponse.json({
          ...DEFAULT_MATCHING_CONFIG,
          thresholds: { auto: 0.9, review: 0.65, visual_min: 0.8 },
        }),
      ),
      http.put(`${API}/admin/matching-config`, async ({ request }) => {
        const body = await request.json();
        saved.push(body);
        return HttpResponse.json(body);
      }),
    );
    const { user } = renderWithProviders(<MatchingSettings />);

    const review = await screen.findByLabelText("Review score");
    expect(review).toHaveValue(0.65);
    expect(
      screen.getByText(/below the auto-link score but at least this/i),
    ).toBeInTheDocument();

    await user.clear(review);
    await user.type(review, "0.95");
    await user.clear(screen.getByLabelText("Distance"));
    await user.type(screen.getByLabelText("Distance"), "0.5");
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    expect(
      screen.getByText("Must be lower than the auto-link score."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Total: 1.10 · The weights must add up to 1."),
    ).toBeInTheDocument();
    expect(review).toHaveAttribute("aria-invalid", "true");
    expect(saved).toEqual([]);

    await user.clear(review);
    await user.type(review, "0.6");
    await user.clear(screen.getByLabelText("Distance"));
    await user.type(screen.getByLabelText("Distance"), "0.4");
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    expect(
      await screen.findByText("Matching settings saved"),
    ).toBeInTheDocument();
    expect(saved[0]).toMatchObject({
      thresholds: { auto: 0.9, review: 0.6, visual_min: 0.8 },
      weights: { geo: 0.4, visual: 0.4, category: 0.1, time: 0.1 },
    });
  });

  it("restores the defaults into the form without saving", async () => {
    signIn();
    const saved: unknown[] = [];
    server.use(
      http.get(`${API}/admin/matching-config`, () =>
        HttpResponse.json({
          ...DEFAULT_MATCHING_CONFIG,
          auto_link_enabled: false,
          thresholds: { auto: 0.95, review: 0.7, visual_min: 0.9 },
        }),
      ),
      http.put(`${API}/admin/matching-config`, async ({ request }) => {
        saved.push(await request.json());
        return HttpResponse.json(DEFAULT_MATCHING_CONFIG);
      }),
    );
    const { user } = renderWithProviders(<MatchingSettings />);
    expect(await screen.findByLabelText("Auto-link score")).toHaveValue(0.95);

    await user.click(screen.getByRole("button", { name: "Restore defaults" }));
    expect(screen.getByLabelText("Auto-link score")).toHaveValue(0.85);
    expect(
      screen.getByRole("checkbox", { name: /link clear duplicates/i }),
    ).toBeChecked();
    expect(
      screen.getByText("Defaults filled in. Save to apply them."),
    ).toBeInTheDocument();
    expect(saved).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Save settings" }));
    await screen.findByText("Matching settings saved");
    expect(saved).toEqual([DEFAULT_MATCHING_CONFIG]);
  });

  it("is read-only without config:manage", async () => {
    signIn(false);
    server.use(
      http.get(`${API}/admin/matching-config`, () =>
        HttpResponse.json(DEFAULT_MATCHING_CONFIG),
      ),
    );
    renderWithProviders(<MatchingSettings />);
    expect(await screen.findByLabelText("Auto-link score")).toBeDisabled();
    expect(screen.getByText(/you can see these settings/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save settings" })).toBeNull();
  });
});

describe("PrioritySettings", () => {
  it("previews an example issue live as the settings change", async () => {
    signIn();
    server.use(
      http.get(`${API}/admin/priority-config`, () =>
        HttpResponse.json(DEFAULT_PRIORITY_CONFIG),
      ),
    );
    const { user } = renderWithProviders(<PrioritySettings />);
    const preview = await screen.findByRole("region", { name: "Preview" });
    // High severity 30 + 3 reporters 11.6 + 10 days 5 + 1 similar 5 + place 10.
    expect(within(preview).getByText("Score 61.6 of 100")).toBeInTheDocument();
    expect(preview).toHaveTextContent("Priority: High");

    const highFrom = screen.getByLabelText("High from");
    await user.clear(highFrom);
    await user.type(highFrom, "65");
    expect(preview).toHaveTextContent("Priority: Medium");

    await user.clear(screen.getByLabelText("Critical from"));
    await user.type(screen.getByLabelText("Critical from"), "50");
    expect(
      within(preview).getByText(
        "Fix the highlighted settings to see the preview.",
      ),
    ).toBeInTheDocument();
  });
});

describe("AiScreen", () => {
  it("lists the models with the active one marked, and quality for a date range", async () => {
    signIn(false);
    const ranges: string[] = [];
    server.use(
      http.get(`${API}/admin/ai/models`, () =>
        HttpResponse.json({
          items: [
            {
              model_id: "clip-vit-b32@onnx-1",
              task: "embedding",
              name: "CLIP ViT-B/32",
              version: "onnx-1",
              source: "example/clip@abc123",
              license: "MIT",
              deployed_at: "2026-11-20T00:00:00Z",
              intended_use: "Photo similarity for duplicate matching",
              metrics: { matching: { visual_min: 0.92 } },
              active: true,
            },
            {
              model_id: "fake@1",
              task: "embedding",
              name: "Fake vision model",
              version: "1",
              source: null,
              license: null,
              deployed_at: null,
              intended_use: null,
              metrics: {},
              active: false,
            },
          ],
        }),
      ),
      http.get(`${API}/admin/categories`, () =>
        HttpResponse.json({ items: [], total: 0, limit: 100, offset: 0 }),
      ),
      http.get(`${API}/admin/ai/quality`, ({ request }) => {
        const url = new URL(request.url);
        ranges.push(
          `${url.searchParams.get("from")}..${url.searchParams.get("to")}`,
        );
        return HttpResponse.json({
          from: url.searchParams.get("from"),
          to: url.searchParams.get("to"),
          classifications: {
            done: 120,
            failed: 6,
            accepted_by_category: { pothole: 40 },
            corrected_by_category: { pothole: 10 },
          },
          matching: { auto_linked: 12, sent_to_review: 9, new_issue: 80 },
          reviews: { linked: 5, new_issue: 4 },
          auto_link_feedback: { correct: 7, incorrect: 1 },
        });
      }),
    );
    renderWithProviders(<AiScreen />);

    const clip = await screen.findByRole("row", { name: /CLIP ViT-B\/32/ });
    expect(within(clip).getByText("In use")).toBeInTheDocument();
    expect(
      within(
        screen.getByRole("row", { name: /Fake vision model/ }),
      ).queryByText("In use"),
    ).toBeNull();

    expect(await screen.findByText("80%")).toBeInTheDocument();
    expect(screen.getByText("7 correct, 1 incorrect")).toBeInTheDocument();

    // jsdom's date input doesn't take typed characters; set it whole.
    fireEvent.change(screen.getByLabelText("From"), {
      target: { value: "2026-11-01" },
    });
    await screen.findByText("80%");
    await vi.waitFor(() => expect(ranges.at(-1)).toMatch(/^2026-11-01\.\./));
  });
});
