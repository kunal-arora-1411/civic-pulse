import { apiRequest, refreshSession } from "../client";
import {
  type OtpChallenge,
  type OtpVerifyResponse,
  otpChallengeSchema,
  otpVerifyResponseSchema,
  type TokenResponse,
  tokenResponseSchema,
} from "../schemas";
import { session } from "../session";

export function requestOtp(phone: string): Promise<OtpChallenge> {
  return apiRequest({
    method: "POST",
    path: "/auth/otp/request",
    body: { phone },
    schema: otpChallengeSchema,
    auth: false,
  });
}

/** Resolves to a token response, or an MFA challenge for MFA-enabled staff. */
export function verifyOtp(body: {
  challenge_id: string;
  code: string;
}): Promise<OtpVerifyResponse> {
  return apiRequest({
    method: "POST",
    path: "/auth/otp/verify",
    body,
    schema: otpVerifyResponseSchema,
    auth: false,
    credentials: "include",
  });
}

export function verifyMfa(body: {
  mfa_token: string;
  code: string;
}): Promise<TokenResponse> {
  return apiRequest({
    method: "POST",
    path: "/auth/mfa/verify",
    body,
    schema: tokenResponseSchema,
    auth: false,
    credentials: "include",
  });
}

/** Store the tokens from a completed OTP or MFA step. */
export function completeLogin(tokens: TokenResponse): void {
  session.setAuthenticated(tokens.access_token, tokens.user);
}

export type RestoreResult = "authenticated" | "anonymous" | "offline";

/**
 * Called once when the app loads. The access token only lives in memory,
 * so every page load starts signed out until the refresh cookie has been
 * exchanged for a new token.
 */
export async function restoreSession(): Promise<RestoreResult> {
  try {
    return (await refreshSession()) ? "authenticated" : "anonymous";
  } catch {
    session.clear();
    return "offline";
  }
}

/**
 * Revoke the session server-side (which also clears the refresh cookie),
 * then forget it locally. Local state is cleared even if the request
 * fails, so the user is never stuck looking signed in. Resolves to whether
 * the server confirmed the revocation.
 */
export async function logout(): Promise<boolean> {
  try {
    if (session.getAccessToken()) {
      await apiRequest({
        method: "POST",
        path: "/auth/logout",
        credentials: "include",
      });
    }
    return true;
  } catch {
    return false;
  } finally {
    session.clear();
  }
}
