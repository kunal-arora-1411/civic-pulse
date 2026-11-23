import { apiRequest } from "../client";
import {
  type OtpChallenge,
  type OtpVerifyResponse,
  otpChallengeSchema,
  otpVerifyResponseSchema,
  type TokenResponse,
  tokenResponseSchema,
} from "../schemas";

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
