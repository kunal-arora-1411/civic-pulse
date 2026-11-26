import { act, screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { session } from "@/lib/api";
import { makeUser, makeWorkOrder } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { WorkOrderList } from "./work-order-list";
import { directionsUrl, WorkOrderScreen } from "./work-order-screen";

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

const WO = `${API}/field/work-orders/wo-1`;

async function renderOrder(id = "wo-1") {
  const params = Promise.resolve({ id });
  let result: ReturnType<typeof renderWithProviders> | undefined;
  await act(async () => {
    result = renderWithProviders(
      <Suspense fallback={null}>
        <WorkOrderScreen params={params} />
      </Suspense>,
    );
    await params;
  });
  return result as ReturnType<typeof renderWithProviders>;
}

beforeEach(() => {
  session.setAuthenticated(
    "token",
    makeUser({
      roles: [
        { role: "field_worker", department_id: null, jurisdiction_id: null },
      ],
      permissions: ["workorder:read_assigned", "workorder:update"],
    }),
  );
  server.use(http.get(`${API}/categories`, () => HttpResponse.json([])));
});
afterEach(() => session.reset());

describe("WorkOrderList", () => {
  it("lists the worker's jobs, new ones first, each linking to its detail", async () => {
    let query = "";
    server.use(
      http.get(`${API}/field/work-orders`, ({ request }) => {
        query = new URL(request.url).search;
        return HttpResponse.json({
          items: [
            makeWorkOrder({ id: "wo-2", state: "in_progress" }),
            makeWorkOrder({
              id: "wo-1",
              issue: { ...makeWorkOrder().issue, reference: "CP-26-000200" },
            }),
          ],
          total: 2,
          limit: 100,
          offset: 0,
        });
      }),
    );
    renderWithProviders(<WorkOrderList />);

    const list = await screen.findByRole("list", { name: "Active" });
    const links = within(list).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/field/work-orders/wo-1",
      "/field/work-orders/wo-2",
    ]);
    expect(within(links[0]).getByText("New")).toBeInTheDocument();
    expect(within(links[0]).getByText("CP-26-000200")).toBeInTheDocument();
    // The default view leaves the state filter to the API.
    expect(query).not.toContain("state=");
  });

  it("asks only for finished jobs on the Done tab", async () => {
    const queries: string[] = [];
    server.use(
      http.get(`${API}/field/work-orders`, ({ request }) => {
        queries.push(new URL(request.url).searchParams.getAll("state").join());
        return HttpResponse.json({
          items: [],
          total: 0,
          limit: 100,
          offset: 0,
        });
      }),
    );
    const { user } = renderWithProviders(<WorkOrderList />);
    expect(await screen.findByText("No work orders yet")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Done" }));
    expect(await screen.findByText("No finished jobs yet")).toBeInTheDocument();
    expect(queries).toEqual(["", "done"]);
  });
});

describe("WorkOrderScreen", () => {
  it("shows the job without any reporter details and links to directions", async () => {
    server.use(http.get(WO, () => HttpResponse.json(makeWorkOrder())));
    await renderOrder();

    expect(
      await screen.findByRole("heading", { name: /pothole/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Deep pothole near the bus stop"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/reporter/i)).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /get directions/i }),
    ).toHaveAttribute("href", directionsUrl({ lat: 12.9716, lng: 77.5946 }));
  });

  it("treats someone else's work order as not found", async () => {
    server.use(
      http.get(WO, () =>
        HttpResponse.json(
          { error: { code: "not_found", message: "Not found" } },
          { status: 404 },
        ),
      ),
    );
    await renderOrder();

    expect(await screen.findByText("Work order not found")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Accept job" }),
    ).not.toBeInTheDocument();
  });

  it("accepts with the version it was looking at", async () => {
    const accept = vi.fn();
    server.use(
      http.get(WO, () => HttpResponse.json(makeWorkOrder())),
      http.post(`${WO}/accept`, async ({ request }) => {
        accept(await request.json());
        return HttpResponse.json(
          makeWorkOrder({ state: "accepted", version: 2 }),
        );
      }),
      http.get(`${API}/field/work-orders`, () =>
        HttpResponse.json({ items: [], total: 0, limit: 100, offset: 0 }),
      ),
    );
    const { user } = await renderOrder();

    await user.click(await screen.findByRole("button", { name: "Accept job" }));

    expect(
      await screen.findByRole("button", { name: "Start work" }),
    ).toBeInTheDocument();
    expect(accept).toHaveBeenCalledWith({ version: 1 });
  });

  it("shows what changed when the job moved on in the meantime", async () => {
    server.use(
      http.get(WO, () => HttpResponse.json(makeWorkOrder())),
      http.post(`${WO}/accept`, () =>
        HttpResponse.json(
          {
            error: {
              code: "version_conflict",
              message: "Changed",
              details: {
                work_order: makeWorkOrder({ state: "cancelled", version: 2 }),
              },
            },
          },
          { status: 409 },
        ),
      ),
    );
    const { user } = await renderOrder();

    await user.click(await screen.findByRole("button", { name: "Accept job" }));

    expect(
      await screen.findByText("This job changed while you had it open"),
    ).toBeInTheDocument();
    expect(screen.getByText(/It's now “Cancelled”/)).toBeInTheDocument();
    expect(screen.getByText("Job reassigned")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Accept job" }),
    ).not.toBeInTheDocument();
  });

  it("needs a reason to decline", async () => {
    const decline = vi.fn();
    server.use(
      http.get(WO, () => HttpResponse.json(makeWorkOrder())),
      http.post(`${WO}/decline`, async ({ request }) => {
        decline(await request.json());
        return HttpResponse.json(
          makeWorkOrder({ state: "declined", version: 2 }),
        );
      }),
    );
    const { user } = await renderOrder();

    await user.click(await screen.findByRole("button", { name: "Decline" }));
    await user.click(screen.getByRole("button", { name: "Decline job" }));
    expect(screen.getByText("Tell your supervisor why.")).toBeInTheDocument();
    expect(decline).not.toHaveBeenCalled();

    await user.type(
      screen.getByLabelText(/why are you declining/i),
      "Needs a road roller",
    );
    await user.click(screen.getByRole("button", { name: "Decline job" }));

    expect(
      await screen.findByText("You declined this job"),
    ).toBeInTheDocument();
    expect(decline).toHaveBeenCalledWith({
      version: 1,
      reason: "Needs a road roller",
    });
  });

  it("posts a progress note", async () => {
    const progress = vi.fn();
    server.use(
      http.get(WO, () =>
        HttpResponse.json(makeWorkOrder({ state: "in_progress", version: 3 })),
      ),
      http.post(`${WO}/progress`, async ({ request }) => {
        progress(await request.json());
        return HttpResponse.json(
          makeWorkOrder({
            state: "in_progress",
            version: 4,
            updates: [
              {
                at: "2026-11-21T11:00:00+05:30",
                note: "Cold mix laid",
                location: null,
              },
            ],
          }),
        );
      }),
    );
    const { user } = await renderOrder();

    await user.click(await screen.findByRole("button", { name: "Add update" }));
    await user.click(screen.getByRole("button", { name: "Post update" }));
    expect(
      screen.getByText("Add a note or at least one photo."),
    ).toBeInTheDocument();
    expect(progress).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/^note/i), "Cold mix laid");
    await user.click(screen.getByRole("button", { name: "Post update" }));

    expect(await screen.findByText("Cold mix laid")).toBeInTheDocument();
    expect(progress).toHaveBeenCalledWith({
      version: 3,
      note: "Cold mix laid",
      location: null,
      media_ids: [],
    });
  });

  it("offers the category's reason codes when closing without a photo", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.get(WO, () =>
        HttpResponse.json(makeWorkOrder({ state: "in_progress", version: 3 })),
      ),
      http.post(`${WO}/request-closure`, async ({ request }) => {
        const body = (await request.json()) as { reason_code?: string };
        bodies.push(body);
        if (!body.reason_code) {
          return HttpResponse.json(
            {
              error: {
                code: "evidence_required",
                message: "After photo needed",
                details: { allowed_reason_codes: ["no_issue_found"] },
              },
            },
            { status: 422 },
          );
        }
        return HttpResponse.json(
          makeWorkOrder({ state: "completion_requested", version: 4 }),
        );
      }),
    );
    const { user } = await renderOrder();

    await user.click(
      await screen.findByRole("button", { name: "Mark as fixed" }),
    );
    await user.click(screen.getByRole("button", { name: "Send for approval" }));

    await user.click(
      await screen.findByRole("radio", { name: "No problem found on site" }),
    );
    await user.click(screen.getByRole("button", { name: "Send for approval" }));

    expect(await screen.findByText("Waiting for approval")).toBeInTheDocument();
    expect(bodies).toEqual([
      { version: 3, media_ids: [] },
      { version: 3, media_ids: [], reason_code: "no_issue_found" },
    ]);
  });
});
