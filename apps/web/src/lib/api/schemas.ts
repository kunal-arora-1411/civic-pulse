import { z } from "zod";

/*
 * Response schemas for the Phase 0 contract (docs/api/phase-0-contract.md).
 * Phase 1 additions live in schemas-phase1.ts.
 *
 * These are hand-written for now. Once the backend publishes openapi.json,
 * orval can generate both the types and zod schemas; the plan is to replace
 * this file with re-exports from the generated package while keeping the
 * exported names, so feature code doesn't change.
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
export const roleSchema = z.enum(ROLES);
export type Role = z.infer<typeof roleSchema>;

export const STAFF_ROLES = [
  "operator",
  "supervisor",
  "field_worker",
  "municipal_admin",
  "platform_admin",
] as const satisfies readonly Role[];

export const roleAssignmentSchema = z.object({
  role: roleSchema,
  department_id: z
    .string()
    .nullish()
    .transform((v) => v ?? null),
  jurisdiction_id: z
    .string()
    .nullish()
    .transform((v) => v ?? null),
});
export type RoleAssignment = z.infer<typeof roleAssignmentSchema>;

export const currentUserSchema = z.object({
  id: z.string(),
  tenant_id: z.string().nullable(),
  phone: z.string(),
  email: z.string().nullable(),
  display_name: z.string().nullable(),
  locale: z.string(),
  preferences: z.record(z.string(), z.unknown()).default({}),
  mfa_enabled: z.boolean(),
  is_staff: z.boolean(),
  roles: z.array(roleAssignmentSchema),
  permissions: z.array(z.string()),
});
export type CurrentUser = z.infer<typeof currentUserSchema>;

export const adminUserSchema = currentUserSchema.extend({
  is_active: z.boolean(),
  created_at: z.string(),
});
export type AdminUser = z.infer<typeof adminUserSchema>;

export const tokenResponseSchema = z.object({
  access_token: z.string().min(1),
  token_type: z.string(),
  expires_in: z.number(),
  refresh_token: z.string().optional(),
  user: currentUserSchema,
});
export type TokenResponse = z.infer<typeof tokenResponseSchema>;

export const mfaChallengeSchema = z.object({
  mfa_required: z.literal(true),
  mfa_token: z.string().min(1),
});
export type MfaChallenge = z.infer<typeof mfaChallengeSchema>;

export const otpVerifyResponseSchema = z.union([
  mfaChallengeSchema,
  tokenResponseSchema,
]);
export type OtpVerifyResponse = z.infer<typeof otpVerifyResponseSchema>;

export const otpChallengeSchema = z.object({
  challenge_id: z.string(),
  expires_in: z.number(),
  resend_after: z.number(),
});
export type OtpChallenge = z.infer<typeof otpChallengeSchema>;

/** GeoJSON order: longitude first. */
export const lngLatSchema = z.tuple([z.number(), z.number()]);
export type LngLatTuple = z.infer<typeof lngLatSchema>;

/** Phase 1: the initial map view, from the city jurisdiction. */
export const tenantMapSchema = z.object({
  center: lngLatSchema,
  zoom: z.number(),
  /** minLng, minLat, maxLng, maxLat */
  bounds: z.tuple([z.number(), z.number(), z.number(), z.number()]),
});
export type TenantMap = z.infer<typeof tenantMapSchema>;

export const tenantSchema = z.object({
  id: z.string(),
  slug: z.string(),
  name: z.string(),
  default_locale: z.string(),
  supported_locales: z.array(z.string()),
  map: tenantMapSchema.nullish(),
});
export type Tenant = z.infer<typeof tenantSchema>;

export const departmentSchema = z.object({
  id: z.string(),
  name: z.string(),
  code: z.string(),
});
export type Department = z.infer<typeof departmentSchema>;

export const jurisdictionSchema = z.object({
  id: z.string(),
  parent_id: z.string().nullable(),
  kind: z.string(),
  name: z.string(),
  code: z.string(),
});
export type Jurisdiction = z.infer<typeof jurisdictionSchema>;

export const auditEventSchema = z.object({
  id: z.union([z.number(), z.string()]),
  occurred_at: z.string(),
  actor: z
    .object({ id: z.string(), display_name: z.string().nullable() })
    .nullable(),
  action: z.string(),
  entity_type: z.string(),
  entity_id: z.string().nullable(),
  before: z.unknown().nullable(),
  after: z.unknown().nullable(),
  request_id: z.string().nullable(),
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
