import { screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { session } from "@/lib/api";
import {
  DRAFT_STORAGE_KEY,
  newDraft,
  type ReportDraft,
} from "@/lib/report/draft";
import {
  makeCategory,
  makeReport,
  makeTenant,
  makeUser,
} from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { ReportFlow } from "./report-flow";

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
  usePathname: () => "/report",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

const pothole = makeCategory({
  evidence: { min_photos: 1, max_photos: 3 },
  fields: [
    {
      key: "size",
      type: "select",
      required: true,
      label_i18n: { en: "Size" },
      options: [
        { value: "small", label_i18n: { en: "Small" } },
        { value: "large", label_i18n: { en: "Large" } },
      ],
    },
  ],
});

function storedDraft(): ReportDraft {
  return JSON.parse(sessionStorage.getItem(DRAFT_STORAGE_KEY) ?? "null");
}

function readyDraft(overrides: Partial<ReportDraft> = {}): ReportDraft {
  return {
    ...newDraft(),
    step: 4,
    photos: [{ id: "p1", mediaId: "media-1", thumbDataUrl: null }],
    location: { lat: 12.9716, lng: 77.5946, accuracyM: 8, source: "gps" },
    addressText: "MG Road",
    wardName: "Ward 3 (synthetic)",
    categoryId: pothole.id,
    details: { size: "large" },
    description: "Deep pothole",
    ...overrides,
  };
}

function useReferenceHandlers(inJurisdiction = true) {
  server.use(
    http.get(`${API}/categories`, () => HttpResponse.json([pothole])),
    // The AI is "down" unless a test says otherwise: the flow must work
    // exactly as before without it.
    http.post(`${API}/ai/classifications`, () =>
      HttpResponse.json({
        id: "cls-down",
        status: "failed",
        error: "ai_unavailable",
      }),
    ),
    http.get(`${API}/tenants/current`, () => HttpResponse.json(makeTenant())),
    http.get(`${API}/geo/reverse`, () =>
      HttpResponse.json({
        address_text: "MG Road",
        in_jurisdiction: inJurisdiction,
        ward: inJurisdiction
          ? { id: "ward-3", name: "Ward 3 (synthetic)", code: "W03" }
          : null,
        zone: null,
      }),
    ),
  );
}

beforeEach(() => {
  sessionStorage.clear();
  session.setAuthenticated("token", makeUser());
  window.history.replaceState(null, "", "/report");
});
afterEach(() => {
  session.reset();
  vi.useRealTimers();
});

describe("ReportFlow submission", () => {
  it("retries a failed submission with the same idempotency key, then starts a new draft with a new key", async () => {
    const draft = readyDraft();
    sessionStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
    useReferenceHandlers();
    const keys: (string | null)[] = [];
    const bodies: unknown[] = [];
    let attempt = 0;
    server.use(
      http.post(`${API}/reports`, async ({ request }) => {
        keys.push(request.headers.get("Idempotency-Key"));
        bodies.push(await request.json());
        attempt += 1;
        if (attempt === 1) return HttpResponse.error();
        return HttpResponse.json(makeReport(), { status: 201 });
      }),
    );
    // Only Date is faked, so the retry happens visibly later without
    // freezing the timers user-event and React Query rely on.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-24T08:15:00Z"));

    const { user } = renderWithProviders(<ReportFlow />);
    await user.click(
      await screen.findByRole("button", { name: /send report/i }),
    );

    expect(
      await screen.findByText(/your report is saved on this phone/i),
    ).toBeInTheDocument();
    // The draft and its key survive the failure.
    expect(storedDraft().idempotencyKey).toBe(draft.idempotencyKey);

    vi.setSystemTime(new Date("2026-11-24T08:16:30Z"));
    await user.click(screen.getByRole("button", { name: /try again/i }));

    expect(
      await screen.findByRole("heading", { name: /report sent/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("R-26-000123")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /view your report/i }),
    ).toHaveAttribute("href", "/reports/rep-1");
    expect(keys).toEqual([draft.idempotencyKey, draft.idempotencyKey]);
    // The API replays a key only for an identical body, so the retry must
    // repeat the first attempt's timestamp rather than take a new one.
    expect(bodies[1]).toEqual(bodies[0]);
    expect(bodies[0]).toMatchObject({
      client_created_at: "2026-11-24T08:15:00.000Z",
    });

    // A new draft replaces the submitted one, with its own key.
    await waitFor(() =>
      expect(storedDraft().idempotencyKey).not.toBe(draft.idempotencyKey),
    );
    expect(storedDraft().photos).toEqual([]);
  });

  it("sends the citizen back to the location step when the API says out of jurisdiction", async () => {
    sessionStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(readyDraft()));
    useReferenceHandlers();
    server.use(
      http.post(`${API}/reports`, () =>
        HttpResponse.json(
          { error: { code: "out_of_jurisdiction", message: "Outside" } },
          { status: 422 },
        ),
      ),
    );

    const { user } = renderWithProviders(<ReportFlow />);
    await user.click(
      await screen.findByRole("button", { name: /send report/i }),
    );

    expect(
      await screen.findByText(/outside the city's area/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /try again/i })).toBeNull();
    await user.click(screen.getByRole("button", { name: /go to location/i }));
    expect(
      await screen.findByRole("heading", { name: /where is the problem/i }),
    ).toBeInTheDocument();
  });

  it("offers to send as a new report when the key was used for different details", async () => {
    const draft = readyDraft();
    sessionStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
    useReferenceHandlers();
    const keys: (string | null)[] = [];
    server.use(
      http.post(`${API}/reports`, ({ request }) => {
        const key = request.headers.get("Idempotency-Key");
        keys.push(key);
        return key === draft.idempotencyKey
          ? HttpResponse.json(
              { error: { code: "idempotency_key_reused", message: "" } },
              { status: 422 },
            )
          : HttpResponse.json(makeReport(), { status: 201 });
      }),
    );

    const { user } = renderWithProviders(<ReportFlow />);
    await user.click(
      await screen.findByRole("button", { name: /send report/i }),
    );
    await user.click(
      await screen.findByRole("button", { name: /send as a new report/i }),
    );

    expect(
      await screen.findByRole("heading", { name: /report sent/i }),
    ).toBeInTheDocument();
    expect(keys).toHaveLength(2);
    expect(keys[1]).not.toBe(draft.idempotencyKey);
  });
});

describe("ReportFlow step validation", () => {
  it("blocks continuing from step 1 without a photo", async () => {
    useReferenceHandlers();
    const { user } = renderWithProviders(<ReportFlow />);
    await user.click(await screen.findByRole("button", { name: /continue/i }));
    expect(
      await screen.findByText(/add at least 1 photo to continue/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /add photos of the problem/i }),
    ).toBeInTheDocument();
  });

  it("warns about and blocks a pin outside the city", async () => {
    sessionStorage.setItem(
      DRAFT_STORAGE_KEY,
      JSON.stringify(readyDraft({ step: 2 })),
    );
    useReferenceHandlers(false);
    const { user } = renderWithProviders(<ReportFlow />);

    expect(
      await screen.findByText(/outside the area demo city looks after/i),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /continue/i }));
    expect(
      screen.getByRole("heading", { name: /where is the problem/i }),
    ).toBeInTheDocument();
  });

  it("requires the category's required fields and re-checks its photo limit", async () => {
    sessionStorage.setItem(
      DRAFT_STORAGE_KEY,
      JSON.stringify(
        readyDraft({
          step: 3,
          details: {},
          photos: Array.from({ length: 4 }, (_, i) => ({
            id: `p${i}`,
            mediaId: `m${i}`,
            thumbDataUrl: null,
          })),
        }),
      ),
    );
    useReferenceHandlers();
    const { user } = renderWithProviders(<ReportFlow />);

    await screen.findByRole("radio", { name: /pothole/i });
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(screen.getByText(/answer this to continue/i)).toBeInTheDocument();
    expect(
      screen.getByText(/allows up to 3 photos\. you've added 4/i),
    ).toBeInTheDocument();
  });
});

describe("ReportFlow category suggestion", () => {
  const waste = makeCategory({
    id: "cat-waste",
    code: "waste",
    name_i18n: { en: "Garbage / waste" },
    icon: "trash-2",
    evidence: { min_photos: 1, max_photos: 3 },
  });
  const drain = makeCategory({
    id: "cat-drain",
    code: "drainage",
    name_i18n: { en: "Blocked drain" },
    icon: "droplets",
    evidence: { min_photos: 1, max_photos: 3 },
  });
  const fast = { debounceMs: 0, pollMs: 10, timeoutMs: 200 };
  const classification = (overrides: Record<string, unknown> = {}) => ({
    id: "cls-1",
    status: "done",
    model_id: "fake@1",
    suggestions: [
      { category_id: "cat-waste", code: "waste", confidence: 0.82 },
      { category_id: "cat-drain", code: "drainage", confidence: 0.1 },
    ],
    not_civic: false,
    needs_manual: false,
    ...overrides,
  });

  function useSuggestionHandlers(result: Record<string, unknown>) {
    useReferenceHandlers();
    server.use(
      http.get(`${API}/categories`, () =>
        HttpResponse.json([pothole, waste, drain]),
      ),
      http.post(`${API}/ai/classifications`, () => HttpResponse.json(result)),
    );
  }

  const atLocation = () =>
    readyDraft({ step: 2, categoryId: null, details: {}, description: "" });

  function captureReports() {
    const bodies: Record<string, unknown>[] = [];
    server.use(
      http.post(`${API}/reports`, async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(makeReport(), { status: 201 });
      }),
    );
    return bodies;
  }

  it("pre-selects the top suggestion, lists suggestions first, and sends the classification id with the citizen's choice", async () => {
    sessionStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(atLocation()));
    useSuggestionHandlers(classification());
    const bodies = captureReports();
    const { user } = renderWithProviders(
      <ReportFlow suggestionTiming={fast} />,
    );

    await waitFor(() => expect(storedDraft().suggestion?.id).toBe("cls-1"));
    await user.click(screen.getByRole("button", { name: /continue/i }));

    const suggested = await screen.findByRole("radio", { name: /garbage/i });
    await waitFor(() => expect(suggested).toBeChecked());
    expect(
      screen.getByText(/this looks like garbage \/ waste\./i),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText("Suggested from your photo").length,
    ).toBeGreaterThan(0);
    // No numbers for citizens.
    expect(screen.queryByText(/%|0\.82/)).toBeNull();
    // Suggestions first, best first, then everything else.
    expect(
      screen.getAllByRole("radio").map((radio) => radio.getAttribute("value")),
    ).toEqual(["cat-waste", "cat-drain", "cat-pothole"]);

    // The citizen knows better: their choice stands.
    await user.click(screen.getByRole("radio", { name: /pothole/i }));
    await user.selectOptions(screen.getByLabelText(/size/i), "large");
    await user.click(screen.getByRole("button", { name: /continue/i }));
    await user.click(
      await screen.findByRole("button", { name: /send report/i }),
    );

    await screen.findByRole("heading", { name: /report sent/i });
    expect(bodies[0]).toMatchObject({
      category_id: "cat-pothole",
      classification_id: "cls-1",
    });
  });

  it("leaves a category the citizen already chose alone", async () => {
    sessionStorage.setItem(
      DRAFT_STORAGE_KEY,
      JSON.stringify(
        readyDraft({
          step: 3,
          categoryId: "cat-pothole",
          categorySource: "citizen",
        }),
      ),
    );
    useSuggestionHandlers(classification());
    renderWithProviders(<ReportFlow suggestionTiming={fast} />);

    await waitFor(() => expect(storedDraft().suggestion?.id).toBe("cls-1"));
    expect(screen.getByRole("radio", { name: /pothole/i })).toBeChecked();
    expect(screen.getByRole("radio", { name: /garbage/i })).not.toBeChecked();
    expect(screen.queryByText(/this looks like/i)).toBeNull();
    expect(storedDraft().classificationId ?? null).toBeNull();
  });

  it("shows a gentle notice for a photo with no civic problem, without blocking", async () => {
    sessionStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(atLocation()));
    useSuggestionHandlers(classification({ not_civic: true, suggestions: [] }));
    const { user } = renderWithProviders(
      <ReportFlow suggestionTiming={fast} />,
    );

    await waitFor(() => expect(storedDraft().suggestion?.id).toBe("cls-1"));
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(
      await screen.findByText("We couldn't spot a civic problem in this photo"),
    ).toBeInTheDocument();
    expect(screen.getByText(/you can still continue/i)).toBeInTheDocument();
    for (const radio of screen.getAllByRole("radio")) {
      expect(radio).not.toBeChecked();
    }

    await user.click(screen.getByRole("radio", { name: /garbage/i }));
    await user.click(screen.getByRole("button", { name: /continue/i }));
    expect(
      await screen.findByRole("button", { name: /send report/i }),
    ).toBeEnabled();
  });

  it("asks for a manual choice, without fuss, when the model isn't sure", async () => {
    sessionStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(atLocation()));
    useSuggestionHandlers(classification({ needs_manual: true }));
    const bodies = captureReports();
    const { user } = renderWithProviders(
      <ReportFlow suggestionTiming={fast} />,
    );

    await waitFor(() => expect(storedDraft().suggestion?.id).toBe("cls-1"));
    await user.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByRole("radio", { name: /garbage/i });
    for (const radio of screen.getAllByRole("radio")) {
      expect(radio).not.toBeChecked();
    }
    expect(screen.queryByText(/suggested from your photo/i)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();

    await user.click(screen.getByRole("radio", { name: /garbage/i }));
    await user.click(screen.getByRole("button", { name: /continue/i }));
    await user.click(
      await screen.findByRole("button", { name: /send report/i }),
    );
    await screen.findByRole("heading", { name: /report sent/i });
    expect(bodies[0]).not.toHaveProperty("classification_id");
  });
});
