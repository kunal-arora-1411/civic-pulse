import type { AdminUser, CurrentUser, TokenResponse } from "@/lib/api/schemas";

/** Builders for API payloads used across tests. Synthetic data only. */
export function makeUser(overrides: Partial<CurrentUser> = {}): CurrentUser {
  return {
    id: "00000000-0000-4000-8000-000000000005",
    tenant_id: "00000000-0000-4000-8000-0000000000aa",
    phone: "+919000000005",
    email: null,
    display_name: "Asha",
    locale: "en",
    preferences: {},
    mfa_enabled: false,
    is_staff: false,
    roles: [{ role: "citizen", department_id: null, jurisdiction_id: null }],
    permissions: ["report:create", "report:read_own"],
    ...overrides,
  };
}

export function makeAdmin(overrides: Partial<CurrentUser> = {}): CurrentUser {
  return makeUser({
    id: "00000000-0000-4000-8000-000000000001",
    phone: "+919000000001",
    display_name: "Meera Admin",
    is_staff: true,
    mfa_enabled: true,
    roles: [
      { role: "municipal_admin", department_id: null, jurisdiction_id: null },
    ],
    permissions: ["user:manage", "audit:read", "config:read", "config:manage"],
    ...overrides,
  });
}

export function makeAdminUser(overrides: Partial<AdminUser> = {}): AdminUser {
  return {
    ...makeUser(),
    is_active: true,
    created_at: "2026-11-01T09:30:00Z",
    ...overrides,
  };
}

export function makeTokenResponse(
  user: CurrentUser = makeUser(),
  accessToken = "access-1",
): TokenResponse {
  return {
    access_token: accessToken,
    token_type: "bearer",
    expires_in: 900,
    refresh_token: "refresh-1",
    user,
  };
}
