import { screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type NotificationPreferences, session } from "@/lib/api";
import { makeUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { NotificationSettings } from "./notification-settings";

const push = vi.hoisted(() => ({
  pushState: vi.fn(),
  enablePush: vi.fn(),
  disablePush: vi.fn(),
}));
vi.mock("@/lib/push", () => push);

function preferences(
  overrides: Partial<NotificationPreferences> = {},
): NotificationPreferences {
  return {
    items: [
      {
        kind: "report_new_issue",
        channels: [
          { channel: "email", enabled: true, default: true },
          { channel: "sms", enabled: true, default: true },
        ],
      },
      {
        kind: "issue_status",
        channels: [
          { channel: "push", enabled: true, default: true },
          { channel: "email", enabled: true, default: true },
          { channel: "sms", enabled: true, default: true },
        ],
      },
    ],
    available: { email: true, sms: true, push: false },
    push_public_key: null,
    ...overrides,
  };
}

beforeEach(() => {
  session.setAuthenticated("token", makeUser());
  push.pushState.mockResolvedValue("unsubscribed");
  push.enablePush.mockResolvedValue("subscribed");
  push.disablePush.mockResolvedValue("unsubscribed");
});
afterEach(() => {
  session.reset();
  vi.clearAllMocks();
});

describe("NotificationSettings", () => {
  it("saves a single choice with PUT and shows the result", async () => {
    let body: unknown;
    server.use(
      http.get(`${API}/notifications/preferences`, () =>
        HttpResponse.json(preferences()),
      ),
      http.put(`${API}/notifications/preferences`, async ({ request }) => {
        body = await request.json();
        const updated = preferences();
        updated.items[1].channels[2].enabled = false;
        return HttpResponse.json(updated);
      }),
    );

    const { user } = renderWithProviders(<NotificationSettings />);
    const sms = await screen.findByRole("checkbox", {
      name: "An issue you reported changed status: SMS",
    });
    expect(sms).toBeChecked();
    // A channel the kind is never sent on has no control at all.
    expect(
      screen.queryByRole("checkbox", {
        name: "Your report started a new issue: Browser",
      }),
    ).not.toBeInTheDocument();

    await user.click(sms);

    await waitFor(() => expect(sms).not.toBeChecked());
    expect(body).toEqual({
      items: [{ kind: "issue_status", channel: "sms", enabled: false }],
    });
  });

  it("explains when the server has no browser notifications", async () => {
    server.use(
      http.get(`${API}/notifications/preferences`, () =>
        HttpResponse.json(
          preferences({ available: { email: false, sms: true, push: false } }),
        ),
      ),
    );
    renderWithProviders(<NotificationSettings />);
    expect(
      await screen.findByText(
        "Browser notifications aren't available from this municipality yet.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Turn on browser notifications" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/Email can't reach you yet/)).toBeInTheDocument();
  });

  it("subscribes this browser with the server's key", async () => {
    server.use(
      http.get(`${API}/notifications/preferences`, () =>
        HttpResponse.json(
          preferences({
            available: { email: true, sms: true, push: true },
            push_public_key: "BKey",
          }),
        ),
      ),
    );
    const { user } = renderWithProviders(<NotificationSettings />);
    await user.click(
      await screen.findByRole("button", {
        name: "Turn on browser notifications",
      }),
    );
    expect(push.enablePush).toHaveBeenCalledWith("BKey");
    expect(
      await screen.findByText("This browser receives notifications."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Turn off on this browser" }),
    ).toBeInTheDocument();
  });

  it("says so when the browser blocked notifications", async () => {
    push.pushState.mockResolvedValue("denied");
    server.use(
      http.get(`${API}/notifications/preferences`, () =>
        HttpResponse.json(preferences({ push_public_key: "BKey" })),
      ),
    );
    renderWithProviders(<NotificationSettings />);
    expect(
      await screen.findByText(/Notifications are blocked for this site/),
    ).toBeInTheDocument();
  });

  it("shows an error when the settings cannot load", async () => {
    server.use(
      http.get(`${API}/notifications/preferences`, () =>
        HttpResponse.json(
          { error: { code: "internal_error", message: "boom" } },
          { status: 500 },
        ),
      ),
    );
    renderWithProviders(<NotificationSettings />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
