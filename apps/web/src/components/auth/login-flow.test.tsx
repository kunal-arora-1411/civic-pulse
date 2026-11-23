import { screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { session } from "@/lib/api";
import { makeAdmin, makeTokenResponse, makeUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { LoginFlow } from "./login-flow";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
vi.mock("@/i18n/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/login",
}));

const challenge = { challenge_id: "ch-1", expires_in: 300, resend_after: 30 };

function errorBody(code: string, details: Record<string, unknown> = {}) {
  return { error: { code, message: code, details, request_id: "req" } };
}

beforeEach(() => {
  session.clear();
  router.replace.mockReset();
});
afterEach(() => session.reset());

describe("LoginFlow", () => {
  it("normalises the phone, then signs in through OTP and MFA", async () => {
    const requests: Record<string, unknown>[] = [];
    let mfaAttempts = 0;
    server.use(
      http.post(`${API}/auth/otp/request`, async ({ request }) => {
        requests.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(challenge);
      }),
      http.post(`${API}/auth/otp/verify`, async ({ request }) => {
        const body = (await request.json()) as { challenge_id: string };
        expect(body).toEqual({ challenge_id: "ch-1", code: "000000" });
        return HttpResponse.json({ mfa_required: true, mfa_token: "mfa-1" });
      }),
      http.post(`${API}/auth/mfa/verify`, async ({ request }) => {
        mfaAttempts += 1;
        const body = (await request.json()) as { code: string };
        if (body.code !== "246810") {
          return HttpResponse.json(
            errorBody("invalid_code", { attempts_remaining: 2 }),
            { status: 400 },
          );
        }
        return HttpResponse.json(makeTokenResponse(makeAdmin(), "admin-token"));
      }),
    );

    const { user } = renderWithProviders(<LoginFlow />);

    await user.type(screen.getByLabelText(/mobile number/i), "098765 43210");
    await user.click(screen.getByRole("button", { name: "Send code" }));

    // Step 2: OTP. Typing the sixth digit submits automatically.
    const otp = await screen.findByLabelText(/6-digit code/i);
    expect(requests).toEqual([{ phone: "+919876543210" }]);
    expect(screen.getByText(/\+91 ••••• •3210/)).toBeInTheDocument();
    expect(otp).toHaveAttribute("autocomplete", "one-time-code");
    expect(
      screen.getByRole("button", { name: /resend code in 0:(29|30)/i }),
    ).toBeDisabled();
    await user.type(otp, "000000");

    // Step 3: MFA. A wrong code explains what happened and how many tries are left.
    const mfa = await screen.findByLabelText(/authenticator code/i);
    await user.type(mfa, "111111");
    expect(
      await screen.findByText(/that code isn't right.*2 attempts left/i),
    ).toBeInTheDocument();
    expect(mfa).toHaveAttribute("aria-invalid", "true");
    expect(session.getSnapshot().status).toBe("anonymous");

    await user.type(mfa, "246810");

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/admin"));
    expect(mfaAttempts).toBe(2);
    expect(session.getAccessToken()).toBe("admin-token");
  });

  it("sends citizens home straight after the OTP step", async () => {
    server.use(
      http.post(`${API}/auth/otp/request`, () => HttpResponse.json(challenge)),
      http.post(`${API}/auth/otp/verify`, () =>
        HttpResponse.json(makeTokenResponse(makeUser())),
      ),
    );

    const { user } = renderWithProviders(<LoginFlow />);
    await user.type(screen.getByLabelText(/mobile number/i), "9000000005");
    await user.click(screen.getByRole("button", { name: "Send code" }));
    await user.type(await screen.findByLabelText(/6-digit code/i), "123456");

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/"));
  });

  it("accepts a pasted code with spaces", async () => {
    let received: unknown;
    server.use(
      http.post(`${API}/auth/otp/request`, () => HttpResponse.json(challenge)),
      http.post(`${API}/auth/otp/verify`, async ({ request }) => {
        received = await request.json();
        return HttpResponse.json(makeTokenResponse(makeUser()));
      }),
    );

    const { user } = renderWithProviders(<LoginFlow />);
    await user.type(screen.getByLabelText(/mobile number/i), "9000000005");
    await user.click(screen.getByRole("button", { name: "Send code" }));
    const otp = await screen.findByLabelText(/6-digit code/i);
    await user.click(otp);
    await user.paste("123 456");

    await waitFor(() =>
      expect(received).toEqual({ challenge_id: "ch-1", code: "123456" }),
    );
  });

  it("rejects an invalid number without calling the API", async () => {
    const { user } = renderWithProviders(<LoginFlow />);
    await user.type(screen.getByLabelText(/mobile number/i), "12345");
    await user.click(screen.getByRole("button", { name: "Send code" }));

    expect(
      await screen.findByText(/enter a valid 10-digit mobile number/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/mobile number/i)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("tells the user how long to wait when rate limited", async () => {
    server.use(
      http.post(`${API}/auth/otp/request`, () =>
        HttpResponse.json(errorBody("rate_limited", { retry_after: 45 }), {
          status: 429,
          headers: { "Retry-After": "45" },
        }),
      ),
    );

    const { user } = renderWithProviders(<LoginFlow />);
    await user.type(screen.getByLabelText(/mobile number/i), "9876543210");
    await user.click(screen.getByRole("button", { name: "Send code" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many attempts. Try again in 45 seconds.",
    );
  });

  it("asks for a new code when the challenge has expired", async () => {
    server.use(
      http.post(`${API}/auth/otp/request`, () => HttpResponse.json(challenge)),
      http.post(`${API}/auth/otp/verify`, () =>
        HttpResponse.json(errorBody("code_expired"), { status: 400 }),
      ),
    );

    const { user } = renderWithProviders(<LoginFlow />);
    await user.type(screen.getByLabelText(/mobile number/i), "9876543210");
    await user.click(screen.getByRole("button", { name: "Send code" }));
    await user.type(await screen.findByLabelText(/6-digit code/i), "999999");

    expect(
      await screen.findByText("This code has expired"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/6-digit code/i)).toBeDisabled();
    expect(screen.getByRole("button", { name: /verify/i })).toBeDisabled();
  });

  it("returns to the phone step when the MFA token expires", async () => {
    server.use(
      http.post(`${API}/auth/otp/request`, () => HttpResponse.json(challenge)),
      http.post(`${API}/auth/otp/verify`, () =>
        HttpResponse.json({ mfa_required: true, mfa_token: "mfa-1" }),
      ),
      http.post(`${API}/auth/mfa/verify`, () =>
        HttpResponse.json(errorBody("code_expired"), { status: 400 }),
      ),
    );

    const { user } = renderWithProviders(<LoginFlow />);
    await user.type(screen.getByLabelText(/mobile number/i), "9876543210");
    await user.click(screen.getByRole("button", { name: "Send code" }));
    await user.type(await screen.findByLabelText(/6-digit code/i), "000000");
    await user.type(await screen.findByLabelText(/authenticator/i), "123456");

    expect(
      await screen.findByText(/two-step verification took too long/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/mobile number/i)).toBeInTheDocument();
  });
});
