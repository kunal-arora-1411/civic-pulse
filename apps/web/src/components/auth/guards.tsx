"use client";

import type { ReactNode } from "react";
import { PageLoading } from "@/components/page-loading";
import { canUseAdmin, canUseField, hasPermission } from "@/lib/auth/access";
import { RequireSession } from "./require-session";

/*
 * Guards are client components because the predicates are functions, which
 * can't be passed from a Server Component layout as props.
 */

export function RequireAuth({ children }: { children: ReactNode }) {
  return <RequireSession>{children}</RequireSession>;
}

/**
 * Wraps the body of every admin page: staff with console access only, and
 * optionally a specific permission. The guard sits in the page rather than
 * the admin layout so the layout always renders its children (see
 * AdminShell).
 */
export function RequireAdminAccess({
  permission,
  children,
}: {
  permission?: string;
  children: ReactNode;
}) {
  return (
    <RequireSession
      fallback={<PageLoading />}
      allow={(user) =>
        canUseAdmin(user) && (!permission || hasPermission(user, permission))
      }
    >
      {children}
    </RequireSession>
  );
}

export function RequireFieldAccess({ children }: { children: ReactNode }) {
  return (
    <RequireSession allow={canUseField} fallback={<PageLoading />}>
      {children}
    </RequireSession>
  );
}
