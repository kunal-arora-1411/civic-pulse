import {
  adminCreateUser,
  adminGetUser,
  adminListAuditEvents,
  adminListDepartments,
  adminListJurisdictions,
  adminListUsers,
  adminReplaceUserRoles,
  adminUpdateUser,
  type JurisdictionKind,
} from "@civicpulse/api-client";
import { call } from "../generated-client";
import {
  type AdminUser,
  type AuditEvent,
  adminUserSchema,
  auditEventSchema,
  type Department,
  departmentSchema,
  type Jurisdiction,
  jurisdictionSchema,
  type Paginated,
  paginated,
  type Role,
} from "../schemas";

export type ListParams = { limit?: number; offset?: number; sort?: string };

export type UserListParams = ListParams & {
  q?: string;
  role?: Role;
  is_active?: boolean;
};

export type RoleAssignmentInput = {
  role: Role;
  department_id?: string | null;
  jurisdiction_id?: string | null;
};

export type CreateUserBody = {
  phone: string;
  display_name: string;
  email?: string;
  roles: RoleAssignmentInput[];
};

export type UpdateUserBody = Partial<{
  display_name: string;
  email: string | null;
  is_active: boolean;
}>;

export type AuditEventParams = ListParams & {
  actor_id?: string;
  action?: string;
  entity_type?: string;
  entity_id?: string;
  /** ISO 8601 timestamps: `from` inclusive, `to` exclusive. */
  from?: string;
  to?: string;
};

const userPage = paginated(adminUserSchema);

export function listUsers(
  params: UserListParams,
  signal?: AbortSignal,
): Promise<Paginated<AdminUser>> {
  return call(userPage, (o) => adminListUsers(params, o), { signal });
}

export function getUser(id: string, signal?: AbortSignal): Promise<AdminUser> {
  return call(adminUserSchema, (o) => adminGetUser(id, o), { signal });
}

/**
 * The caller owns the idempotency key: generate it once per logical
 * "create" and reuse it when retrying after a timeout, so a request that
 * actually succeeded isn't applied twice.
 */
export function createUser(
  body: CreateUserBody,
  options: { idempotencyKey: string },
): Promise<AdminUser> {
  return call(adminUserSchema, (o) => adminCreateUser(body, o), {
    idempotencyKey: options.idempotencyKey,
  });
}

export function updateUser(
  id: string,
  body: UpdateUserBody,
): Promise<AdminUser> {
  return call(adminUserSchema, (o) => adminUpdateUser(id, body, o));
}

export function replaceUserRoles(
  id: string,
  roles: RoleAssignmentInput[],
): Promise<AdminUser> {
  return call(adminUserSchema, (o) => adminReplaceUserRoles(id, { roles }, o));
}

export function listDepartments(
  signal?: AbortSignal,
): Promise<Paginated<Department>> {
  return call(
    paginated(departmentSchema),
    (o) => adminListDepartments({ limit: 100 }, o),
    { signal },
  );
}

export function listJurisdictions(
  params: { kind?: JurisdictionKind } = {},
  signal?: AbortSignal,
): Promise<Paginated<Jurisdiction>> {
  return call(
    paginated(jurisdictionSchema),
    (o) => adminListJurisdictions({ limit: 100, ...params }, o),
    { signal },
  );
}

export function listAuditEvents(
  params: AuditEventParams,
  signal?: AbortSignal,
): Promise<Paginated<AuditEvent>> {
  return call(
    paginated(auditEventSchema),
    (o) => adminListAuditEvents(params, o),
    { signal },
  );
}
