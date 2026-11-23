import { apiRequest } from "../client";
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
  /** ISO 8601 timestamps. */
  from?: string;
  to?: string;
};

const userPage = paginated(adminUserSchema);

export function listUsers(
  params: UserListParams,
  signal?: AbortSignal,
): Promise<Paginated<AdminUser>> {
  return apiRequest({
    path: "/admin/users",
    query: params,
    schema: userPage,
    signal,
  });
}

export function getUser(id: string, signal?: AbortSignal): Promise<AdminUser> {
  return apiRequest({
    path: `/admin/users/${encodeURIComponent(id)}`,
    schema: adminUserSchema,
    signal,
  });
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
  return apiRequest({
    method: "POST",
    path: "/admin/users",
    body,
    schema: adminUserSchema,
    idempotencyKey: options.idempotencyKey,
  });
}

export function updateUser(
  id: string,
  body: UpdateUserBody,
): Promise<AdminUser> {
  return apiRequest({
    method: "PATCH",
    path: `/admin/users/${encodeURIComponent(id)}`,
    body,
    schema: adminUserSchema,
  });
}

export function replaceUserRoles(
  id: string,
  roles: RoleAssignmentInput[],
): Promise<AdminUser> {
  return apiRequest({
    method: "PUT",
    path: `/admin/users/${encodeURIComponent(id)}/roles`,
    body: { roles },
    schema: adminUserSchema,
  });
}

export function listDepartments(
  signal?: AbortSignal,
): Promise<Paginated<Department>> {
  return apiRequest({
    path: "/admin/departments",
    query: { limit: 100 },
    schema: paginated(departmentSchema),
    signal,
  });
}

export function listJurisdictions(
  params: { kind?: string } = {},
  signal?: AbortSignal,
): Promise<Paginated<Jurisdiction>> {
  return apiRequest({
    path: "/admin/jurisdictions",
    query: { limit: 100, ...params },
    schema: paginated(jurisdictionSchema),
    signal,
  });
}

export function listAuditEvents(
  params: AuditEventParams,
  signal?: AbortSignal,
): Promise<Paginated<AuditEvent>> {
  return apiRequest({
    path: "/admin/audit-events",
    query: params,
    schema: paginated(auditEventSchema),
    signal,
  });
}
