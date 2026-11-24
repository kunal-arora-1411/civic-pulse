import { screen, waitFor } from "@testing-library/react";
import { http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { session } from "@/lib/api";
import { apiError, supportHandlers } from "@/test/community";
import { makeAdmin, makeUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { SupportButton } from "./support-button";

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

function renderButton(open = true) {
  return renderWithProviders(
    <SupportButton
      issueId="iss-1"
      count={5}
      open={open}
      returnTo="/track/iss-1"
    />,
  );
}

describe("SupportButton", () => {
  it("asks signed-out visitors to sign in and comes back afterwards", () => {
    session.clear();
    renderButton();
    expect(
      screen.getByRole("link", { name: "Sign in to say you face this too" }),
    ).toHaveAttribute("href", "/login?next=%2Ftrack%2Fiss-1");
    expect(screen.getByText("5 people face this")).toBeInTheDocument();
  });

  it("toggles support at once and keeps the server's count", async () => {
    session.setAuthenticated("token", makeUser());
    server.use(...supportHandlers({ count: 5, supported: false }));
    const { user } = renderButton();

    const button = await screen.findByRole("button", {
      name: "I face this too",
    });
    await waitFor(() => expect(button).toBeEnabled());
    expect(button).toHaveAttribute("aria-pressed", "false");

    await user.click(button);
    const pressed = await screen.findByRole("button", {
      name: "You face this too",
    });
    expect(pressed).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("6 people face this")).toBeInTheDocument();

    await user.click(pressed);
    expect(
      await screen.findByRole("button", { name: "I face this too" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("5 people face this")).toBeInTheDocument();
  });

  it("rolls back and explains when the server refuses", async () => {
    session.setAuthenticated("token", makeUser());
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(...supportHandlers({ count: 5, supported: false }));
    // Registered later, so it wins over the stateful POST above.
    server.use(
      http.post(`${API}/issues/:id/support`, async () => {
        await held;
        return apiError(422, "issue_merged");
      }),
    );
    const { user } = renderButton();
    const button = await screen.findByRole("button", {
      name: "I face this too",
    });
    await waitFor(() => expect(button).toBeEnabled());

    await user.click(button);
    // Optimistic: the count moves before the server answers.
    expect(await screen.findByText("6 people face this")).toBeInTheDocument();
    release();

    expect(
      await screen.findByText(
        "This issue was combined with another one. Support that one instead.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("5 people face this")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "I face this too" }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("shows staff the count only, since they can't support", async () => {
    session.setAuthenticated("token", makeAdmin());
    server.use(
      http.get(`${API}/issues/:id/support`, () => apiError(403, "forbidden")),
    );
    renderButton();
    await waitFor(() =>
      expect(screen.queryByRole("button")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("5 people face this")).toBeInTheDocument();
  });

  it("shows only the count on a closed issue", () => {
    session.setAuthenticated("token", makeUser());
    renderButton(false);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("5 people face this")).toBeInTheDocument();
  });
});
