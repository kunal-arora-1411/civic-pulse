import { type CurrentUser, type Role, STAFF_ROLES } from "@/lib/api";

/*
 * Client-side access helpers. These decide what to *show*; the API makes
 * the real decision on every request. Hiding a link here is a courtesy,
 * not a control.
 */

export function hasPermission(
  user: CurrentUser | null | undefined,
  permission: string,
): boolean {
  return Boolean(user?.permissions.includes(permission));
}

export function hasRole(
  user: CurrentUser | null | undefined,
  role: Role,
): boolean {
  return Boolean(user?.roles.some((assignment) => assignment.role === role));
}

function staffRolesOf(user: CurrentUser): Role[] {
  return user.roles
    .map((assignment) => assignment.role)
    .filter((role) => (STAFF_ROLES as readonly Role[]).includes(role));
}

/** Can open the /admin console: any staff role other than field work. */
export function canUseAdmin(user: CurrentUser | null | undefined): boolean {
  if (!user) return false;
  const staff = staffRolesOf(user);
  if (staff.length === 0) return user.is_staff;
  return staff.some((role) => role !== "field_worker");
}

export function canUseField(user: CurrentUser | null | undefined): boolean {
  return hasRole(user, "field_worker");
}

export type HomePath = "/" | "/admin" | "/field";

/**
 * Where to land after signing in: staff go to the admin console, field
 * workers with no other staff role go to the field app, everyone else to
 * the citizen home.
 */
export function homePathFor(user: CurrentUser): HomePath {
  if (canUseAdmin(user)) return "/admin";
  if (canUseField(user)) return "/field";
  return "/";
}

/**
 * Accept only same-origin absolute paths for the post-login redirect, so
 * `?next=` can't be used to bounce someone to another site.
 */
export function safeNextPath(next: string | null | undefined): string | null {
  if (!next || !next.startsWith("/")) return null;
  if (next.startsWith("//") || next.startsWith("/\\")) return null;
  if (next === "/login" || next.startsWith("/login?")) return null;
  return next;
}
