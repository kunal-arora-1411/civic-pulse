"use client";

import { type ReactNode, useEffect } from "react";
import { PageLoading } from "@/components/page-loading";
import { usePathname, useRouter } from "@/i18n/navigation";
import type { CurrentUser } from "@/lib/api";
import { useSession } from "@/lib/auth/use-session";
import { NotAuthorised } from "./not-authorised";

/**
 * Client-side route guard. It only shapes the UX: signed-out visitors are
 * sent to /login and the wrong role sees a clear "not authorised" page.
 * Security comes from the API, which checks every request itself; nothing
 * rendered here is sensitive until the API has returned it.
 */
export function RequireSession({
  allow,
  children,
  fallback,
}: {
  /** Extra check on the signed-in user (role, permission). */
  allow?: (user: CurrentUser) => boolean;
  children: ReactNode;
  /** Rendered while the session is being restored. */
  fallback?: ReactNode;
}) {
  const { status, user } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "anonymous") {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [status, pathname, router]);

  if (status !== "authenticated" || !user) {
    return fallback ?? <PageLoading className="p-4 sm:p-8" />;
  }
  if (allow && !allow(user)) {
    return <NotAuthorised user={user} />;
  }
  return children;
}
