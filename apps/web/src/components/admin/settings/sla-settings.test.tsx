import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { session } from "@/lib/api";
import { makeAdmin, makeCategory } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { SlaSettings } from "./sla-settings";

afterEach(() => session.reset());

function signIn(manage = true) {
  session.setAuthenticated(
    "token",
    makeAdmin({
      permissions: manage ? ["config:read", "config:manage"] : ["config:read"],
    }),
  );
}

const CATEGORIES = {
  items: [
    makeCategory(),
    makeCategory({
      id: "cat-waste",
      code: "waste",
      name_i18n: { en: "Garbage", hi: "कचरा" },
    }),
  ],
  total: 2,
  limit: 100,
  offset: 0,
};

const TARGETS = {
  items: [
    {
      id: "t1",
      category_id: "cat-pothole",
      priority_band: null,
      resolve_hours: 72,
      escalate_after_hours: 24,
    },
    {
      id: "t2",
      category_id: "cat-pothole",
      priority_band: "critical",
      resolve_hours: 8,
      escalate_after_hours: 24,
    },
  ],
};

function mockApi(saved: unknown[]) {
  server.use(
    http.get(`${API}/admin/categories`, () => HttpResponse.json(CATEGORIES)),
    http.get(`${API}/admin/sla-targets`, () => HttpResponse.json(TARGETS)),
    http.put(`${API}/admin/sla-targets`, async ({ request }) => {
      const body = (await request.json()) as { items: object[] };
      saved.push(body);
      return HttpResponse.json({
        items: body.items.map((item, i) => ({ id: `n${i}`, ...item })),
      });
    }),
  );
}

describe("SlaSettings", () => {
  it("shows the targets per category and band and saves the whole set", async () => {
    signIn();
    const saved: { items: unknown[] }[] = [];
    mockApi(saved);
    const { user } = renderWithProviders(<SlaSettings />);

    const all = await screen.findByLabelText(
      "Pothole / road damage: All bands, hours",
    );
    expect(all).toHaveValue(72);
    expect(
      screen.getByLabelText("Pothole / road damage: Critical, hours"),
    ).toHaveValue(8);
    const garbage = screen.getByLabelText("Garbage: All bands, hours");
    expect(garbage).toHaveValue(null);

    // A target without an escalation time, and an impossible value.
    await user.type(garbage, "48");
    await user.clear(all);
    await user.type(all, "0");
    await user.click(screen.getByRole("button", { name: "Save settings" }));
    expect(
      screen.getByText(
        "Garbage, Escalate after: Enter when to escalate: this category has a target.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Pothole / road damage, All bands: Enter whole hours from 1 to 8760.",
      ),
    ).toBeInTheDocument();
    expect(all).toHaveAttribute("aria-invalid", "true");
    expect(saved).toEqual([]);

    await user.clear(all);
    await user.type(all, "96");
    await user.type(
      screen.getByLabelText("Garbage: Escalate after, hours"),
      "12",
    );
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    expect(await screen.findByText("SLA targets saved")).toBeInTheDocument();
    expect(saved[0]?.items).toEqual(
      expect.arrayContaining([
        {
          category_id: "cat-pothole",
          priority_band: null,
          resolve_hours: 96,
          escalate_after_hours: 24,
        },
        {
          category_id: "cat-pothole",
          priority_band: "critical",
          resolve_hours: 8,
          escalate_after_hours: 24,
        },
        {
          category_id: "cat-waste",
          priority_band: null,
          resolve_hours: 48,
          escalate_after_hours: 12,
        },
      ]),
    );
    expect(saved[0]?.items).toHaveLength(3);
  });

  it("is read-only without config:manage", async () => {
    signIn(false);
    mockApi([]);
    renderWithProviders(<SlaSettings />);
    expect(
      await screen.findByLabelText("Pothole / road damage: All bands, hours"),
    ).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Save settings" }),
    ).not.toBeInTheDocument();
  });
});
