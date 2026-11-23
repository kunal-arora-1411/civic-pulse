"use client";

import type { ReactNode } from "react";
import { canUseAdmin, canUseField, hasPermission } from "@/lib/auth/access";
import { RequireSession } from "./require-session";

/*
 * Guards are client components because the predicates are functions, which
 * can't be passed from a Server Component layout as props.
 */

export function RequireAuth({ children }: { children: ReactNode }) {
  return <RequireSession>{children}</RequireSession>;
}

export function RequireAdminAccess({ children }: { children: ReactNode }) {
  return <RequireSession allow={canUseAdmin}>{children}</RequireSession>;
}

export function RequireFieldAccess({ children }: { children: ReactNode }) {
  return <RequireSession allow={canUseField}>{children}</RequireSession>;
}

/** For pages inside a shell that has already checked the session. */
export function RequirePermission({
  permission,
  children,
}: {
  permission: string;
  children: ReactNode;
}) {
  return (
    <RequireSession allow={(user) => hasPermission(user, permission)}>
      {children}
    </RequireSession>
  );
}
