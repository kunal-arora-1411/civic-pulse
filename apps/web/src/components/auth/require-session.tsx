"use client";

import { type ReactNode, useEffect } from "react";
import { PageLoading } from "@/components/page-loading";
import { useRouter } from "@/i18n/navigation";
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

  useEffect(() => {
    if (status === "anonymous") {
      // Read the URL here rather than through usePathname(). On a dynamic
      // route (/reports/[id]) the pathname is runtime data, and calling
      // the hook during render would push the whole page out of the
      // static shell. This also keeps the query string, so a shared
      // /admin/issues?status=… link survives the trip through sign-in.
      const { pathname, search } = window.location;
      router.replace(`/login?next=${encodeURIComponent(pathname + search)}`);
    }
  }, [status, router]);

  if (status !== "authenticated" || !user) {
    return fallback ?? <PageLoading className="p-4 sm:p-8" />;
  }
  if (allow && !allow(user)) {
    return <NotAuthorised user={user} />;
  }
  return children;
}
