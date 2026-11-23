"use client";

import { Menu, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { type ReactNode, useId, useLayoutEffect, useState } from "react";
import { AccountMenu } from "@/components/account-menu";
import { RequireSession } from "@/components/auth/require-session";
import { Logo } from "@/components/brand/logo";
import { LanguageSwitcher } from "@/components/language-switcher";
import { PageLoading } from "@/components/page-loading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Link } from "@/i18n/navigation";
import type { CurrentUser } from "@/lib/api";
import { canUseAdmin } from "@/lib/auth/access";
import { useSession } from "@/lib/auth/use-session";
import { formatIndianPhone } from "@/lib/phone";
import { AdminNav } from "./admin-nav";

function Frame({
  sidebar,
  mobileNav,
  children,
}: {
  sidebar: ReactNode;
  mobileNav?: (close: () => void) => ReactNode;
  children: ReactNode;
}) {
  const t = useTranslations("admin");
  const [menuOpen, setMenuOpen] = useState(false);
  const menuId = useId();
  useLayoutEffect(() => () => setMenuOpen(false), []);

  return (
    <div className="flex min-h-dvh flex-1 bg-muted/40">
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-e border-border bg-card lg:flex">
        <div className="flex h-16 items-center gap-2 px-5">
          <Link href="/admin" className="rounded-lg">
            <Logo />
          </Link>
        </div>
        <div className="flex flex-1 flex-col justify-between overflow-y-auto px-3 pt-2 pb-4">
          {sidebar}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 border-b border-border bg-card/90 backdrop-blur">
          <div className="flex h-16 items-center justify-between gap-3 px-4 sm:px-6">
            <div className="flex items-center gap-2">
              {mobileNav ? (
                <Button
                  variant="ghost"
                  size="icon"
                  className="lg:hidden"
                  aria-expanded={menuOpen}
                  aria-controls={menuId}
                  aria-label={menuOpen ? t("closeMenu") : t("openMenu")}
                  onClick={() => setMenuOpen((open) => !open)}
                >
                  {menuOpen ? (
                    <X aria-hidden="true" />
                  ) : (
                    <Menu aria-hidden="true" />
                  )}
                </Button>
              ) : null}
              <Link href="/admin" className="rounded-lg lg:hidden">
                <Logo className="[&>span:last-child]:hidden sm:[&>span:last-child]:inline" />
              </Link>
              <Badge variant="outline" className="hidden lg:inline-flex">
                {t("consoleBadge")}
              </Badge>
            </div>
            <div className="flex items-center gap-2 sm:gap-3">
              <LanguageSwitcher />
              <AccountMenu />
            </div>
          </div>
          {mobileNav ? (
            <div
              id={menuId}
              hidden={!menuOpen}
              className="border-t border-border px-4 py-3 lg:hidden"
            >
              {mobileNav(() => setMenuOpen(false))}
            </div>
          ) : null}
        </header>
        <main id="main" className="flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <div className="mx-auto max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  );
}

function SidebarFooter({ user }: { user: CurrentUser }) {
  const t = useTranslations("roles");
  return (
    <div className="mt-6 rounded-xl border border-border bg-muted/50 p-3 text-sm">
      <p className="truncate font-semibold">
        {user.display_name || formatIndianPhone(user.phone)}
      </p>
      <p className="truncate text-muted-foreground">
        {user.roles
          .filter((assignment) => assignment.role !== "citizen")
          .map((assignment) => t(assignment.role))
          .join(", ")}
      </p>
    </div>
  );
}

function ShellSkeleton() {
  return (
    <Frame
      sidebar={
        <div className="grid gap-2">
          <Skeleton className="h-9" />
          <Skeleton className="h-9" />
          <Skeleton className="h-9" />
        </div>
      }
    >
      <PageLoading />
    </Frame>
  );
}

/**
 * Admin console chrome: sidebar on large screens, a disclosure menu on
 * small ones. Navigation is filtered by the user's permissions; each page
 * still checks its own permission, and the API enforces it.
 */
export function AdminShell({ children }: { children: ReactNode }) {
  return (
    <RequireSession allow={canUseAdmin} fallback={<ShellSkeleton />}>
      <AdminFrame>{children}</AdminFrame>
    </RequireSession>
  );
}

function AdminFrame({ children }: { children: ReactNode }) {
  // RequireSession only renders this once the user is known.
  const user = useSessionUser();
  return (
    <Frame
      sidebar={
        <>
          <AdminNav user={user} />
          <SidebarFooter user={user} />
        </>
      }
      mobileNav={(close) => <AdminNav user={user} onNavigate={close} />}
    >
      {children}
    </Frame>
  );
}

function useSessionUser(): CurrentUser {
  const { user } = useSession();
  if (!user) throw new Error("AdminFrame rendered without a user");
  return user;
}
