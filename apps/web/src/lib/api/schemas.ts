import {
  AuditEventOut,
  DepartmentOut,
  AdminUser as GenAdminUser,
  Role as GenRole,
  RoleAssignment as GenRoleAssignment,
  TokenResponse as GenTokenResponse,
  JurisdictionOut,
  MapConfig,
  MfaChallengeResponse,
  OtpRequestOut,
  TenantCurrent,
  UserMe,
} from "@civicpulse/api-client";
import { z } from "zod";
import { expectType, type Same } from "./type-checks";

/*
 * Response schemas for the Phase 0 contract (docs/api/phase-0-contract.md):
 * users, auth, tenant and the admin screens.
 *
 * Built from the orval-generated schemas in @civicpulse/api-client. Where
 * the app needs something the spec doesn't say (a default, `null` instead
 * of a missing key, a field the UI doesn't read yet left optional), the
 * adapter is applied here with a comment, so feature code keeps its types
 * and the exported names stay the same.
 */

/**
 * Kept as a literal tuple: feature code builds `z.enum(ROLES)` and select
 * options from it. The check below fails typecheck if the spec's role list
 * changes.
 */
export const ROLES = [
  "citizen",
  "community_contributor",
  "operator",
  "supervisor",
  "field_worker",
  "municipal_admin",
  "platform_admin",
] as const;
expectType<Same<(typeof ROLES)[number], GenRole>>(true);
export const roleSchema = GenRole;
export type Role = z.infer<typeof roleSchema>;

export const STAFF_ROLES = [
  "operator",
  "supervisor",
  "field_worker",
  "municipal_admin",
  "platform_admin",
] as const satisfies readonly Role[];

// Adapter: the spec lets `department_id` and `jurisdiction_id` be absent;
// the app always reads them as `string | null`.
export const roleAssignmentSchema = GenRoleAssignment.extend({
  department_id: GenRoleAssignment.shape.department_id.transform(
    (v) => v ?? null,
  ),
  jurisdiction_id: GenRoleAssignment.shape.jurisdiction_id.transform(
    (v) => v ?? null,
  ),
});
export type RoleAssignment = z.infer<typeof roleAssignmentSchema>;

// Adapter: `preferences` defaults to `{}` (the spec requires it; the app
// has always tolerated it missing).
export const currentUserSchema = UserMe.extend({
  preferences: UserMe.shape.preferences.default({}),
  roles: z.array(roleAssignmentSchema),
});
export type CurrentUser = z.infer<typeof currentUserSchema>;

// Adapter: same as the current user, and `last_login_at` (required in the
// spec) is optional here; no screen reads it yet and fixtures omit it.
export const adminUserSchema = GenAdminUser.extend({
  preferences: GenAdminUser.shape.preferences.default({}),
  roles: z.array(roleAssignmentSchema),
  last_login_at: GenAdminUser.shape.last_login_at.optional(),
});
export type AdminUser = z.infer<typeof adminUserSchema>;

// Adapters: an empty access token is rejected (it would be sent as a
// bearer token), and `refresh_token` stays optional: the browser keeps the
// HttpOnly cookie and ignores the body copy.
export const tokenResponseSchema = GenTokenResponse.extend({
  access_token: GenTokenResponse.shape.access_token.min(1),
  refresh_token: GenTokenResponse.shape.refresh_token.optional(),
  user: currentUserSchema,
});
export type TokenResponse = z.infer<typeof tokenResponseSchema>;

// Adapter: `mfa_required` must be present (the spec defaults it), because
// it is what tells this shape apart from a token response.
export const mfaChallengeSchema = MfaChallengeResponse.extend({
  mfa_required: z.literal(true),
  mfa_token: MfaChallengeResponse.shape.mfa_token.min(1),
});
export type MfaChallenge = z.infer<typeof mfaChallengeSchema>;

export const otpVerifyResponseSchema = z.union([
  mfaChallengeSchema,
  tokenResponseSchema,
]);
export type OtpVerifyResponse = z.infer<typeof otpVerifyResponseSchema>;

export const otpChallengeSchema = OtpRequestOut;
export type OtpChallenge = z.infer<typeof otpChallengeSchema>;

/** GeoJSON order: longitude first. */
export const lngLatSchema = MapConfig.shape.center;
export type LngLatTuple = z.infer<typeof lngLatSchema>;

/** Phase 1: the initial map view, from the city jurisdiction. */
export const tenantMapSchema = MapConfig;
export type TenantMap = z.infer<typeof tenantMapSchema>;

// Adapter: `map` may also be absent (the spec says present-or-null).
export const tenantSchema = TenantCurrent.extend({
  map: TenantCurrent.shape.map.optional(),
});
export type Tenant = z.infer<typeof tenantSchema>;

// Adapter: only the fields the pickers use; `is_active` and `created_at`
// aren't read anywhere yet.
export const departmentSchema = DepartmentOut.pick({
  id: true,
  name: true,
  code: true,
});
export type Department = z.infer<typeof departmentSchema>;

// Adapter: `kind` stays a plain string so a new jurisdiction kind on the
// server doesn't break the admin screens; geometry is in
// jurisdictionWithGeometrySchema.
export const jurisdictionSchema = JurisdictionOut.omit({
  geometry: true,
}).extend({ kind: z.string() });
export type Jurisdiction = z.infer<typeof jurisdictionSchema>;

// Adapter: `before`/`after` are snapshots the UI only pretty-prints, so any
// JSON is accepted (the spec says object or null).
export const auditEventSchema = AuditEventOut.extend({
  before: z.unknown().nullable(),
  after: z.unknown().nullable(),
});
export type AuditEvent = z.infer<typeof auditEventSchema>;

export function paginated<T extends z.ZodType>(item: T) {
  return z.object({
    items: z.array(item),
    total: z.number(),
    limit: z.number(),
    offset: z.number(),
  });
}
export type Paginated<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};
