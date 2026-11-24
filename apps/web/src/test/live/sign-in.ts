import {
  completeLogin,
  isApiError,
  requestOtp,
  session,
  type TokenResponse,
  verifyOtp,
} from "@/lib/api";

/** Seeded accounts (docs/api/phase-0-contract.md); dev OTP is 000000. */
export const PHONES = {
  municipalAdmin: "+919000000001",
  operator: "+919000000002",
  supervisor: "+919000000003",
  fieldWorker: "+919000000004",
  citizen: "+919000000005",
} as const;

// One sign-in per role per test file: each phone may request a code only
// once every 30 seconds. Vitest isolates files, so a second file can still
// hit the cooldown; requestCode waits it out instead of failing.
const tokens = new Map<keyof typeof PHONES, TokenResponse>();

async function requestCode(phone: string) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await requestOtp(phone);
    } catch (error) {
      if (!isApiError(error, "rate_limited") || attempt >= 2) throw error;
      const seconds = (error.retryAfter ?? 30) + 1;
      await new Promise((resolve) => setTimeout(resolve, seconds * 1000));
    }
  }
}

export async function signInAs(role: keyof typeof PHONES): Promise<void> {
  session.clear();
  let token = tokens.get(role);
  if (!token) {
    const challenge = await requestCode(PHONES[role]);
    const result = await verifyOtp({
      challenge_id: challenge.challenge_id,
      code: "000000",
    });
    if (!("access_token" in result)) {
      throw new Error(
        `${role} needs MFA; run the stack with REQUIRE_STAFF_MFA=false`,
      );
    }
    token = result;
    tokens.set(role, token);
  }
  completeLogin(token);
}
