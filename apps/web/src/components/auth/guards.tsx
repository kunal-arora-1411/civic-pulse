"use client";

import type { ReactNode } from "react";
import { canUseAdmin, canUseField } from "@/lib/auth/access";
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
