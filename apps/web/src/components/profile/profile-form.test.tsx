import { screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { session } from "@/lib/api";
import { makeUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { ProfileForm } from "./profile-form";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
vi.mock("@/i18n/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/profile",
}));

const asha = makeUser({ display_name: "Asha", email: null, locale: "en" });

beforeEach(() => {
  router.replace.mockReset();
  session.setAuthenticated("token", asha);
});
afterEach(() => session.reset());

describe("ProfileForm", () => {
  it("saves name and email through PATCH /users/me", async () => {
    let body: unknown;
    server.use(
      http.patch(`${API}/users/me`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({
          ...asha,
          display_name: "Asha Rao",
          email: "asha@example.org",
        });
      }),
    );

    const { user } = renderWithProviders(<ProfileForm user={asha} />);
    expect(screen.getByText("+91 90000 00005")).toBeInTheDocument();

    const save = screen.getByRole("button", { name: "Save changes" });
    expect(save).toBeDisabled();

    await user.clear(screen.getByLabelText(/display name/i));
    await user.type(screen.getByLabelText(/display name/i), "Asha Rao");
    await user.type(screen.getByLabelText(/email/i), "asha@example.org");
    await user.click(save);

    expect(await screen.findByText("Profile saved")).toBeInTheDocument();
    expect(body).toEqual({
      display_name: "Asha Rao",
      email: "asha@example.org",
      locale: "en",
    });
    expect(session.getSnapshot().user?.display_name).toBe("Asha Rao");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("switches the interface when the language preference changes", async () => {
    server.use(
      http.patch(`${API}/users/me`, () =>
        HttpResponse.json({ ...asha, locale: "hi" }),
      ),
    );

    const { user } = renderWithProviders(<ProfileForm user={asha} />);
    await user.selectOptions(screen.getByLabelText(/^language/i), "hi");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/profile", { locale: "hi" }),
    );
  });

  it("validates the email before saving", async () => {
    const { user } = renderWithProviders(<ProfileForm user={asha} />);
    await user.type(screen.getByLabelText(/email/i), "not-an-email");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(
      await screen.findByText(/enter a valid email address/i),
    ).toBeInTheDocument();
  });
});
