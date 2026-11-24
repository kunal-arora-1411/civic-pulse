"use client";

import { Menu, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { type ReactNode, useId, useLayoutEffect, useState } from "react";
import { AccountMenu } from "@/components/account-menu";
import { TenantName } from "@/components/auth/tenant-name";
import { BrandArcs } from "@/components/brand/brand-arcs";
import { Logo } from "@/components/brand/logo";
import { LanguageSwitcher } from "@/components/language-switcher";
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
    <div className="flex min-h-dvh flex-1 bg-background">
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col overflow-hidden bg-panel text-panel-foreground lg:flex">
        <BrandArcs className="absolute -start-16 bottom-0 h-72 w-80 opacity-25" />
        <div className="relative flex h-16 items-center gap-2 px-5">
          <Link href="/admin" className="rounded-lg">
            <Logo />
          </Link>
        </div>
        <p className="eyebrow relative px-5 pb-3 text-panel-muted-foreground">
          {t("consoleBadge")}
        </p>
        <div className="relative flex flex-1 flex-col justify-between overflow-y-auto px-3 pt-1 pb-4">
          {sidebar}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 border-b border-border/70 bg-background/80 backdrop-blur-md">
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
              <span className="hidden lg:block">
                <TenantName />
              </span>
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
        <main id="main" className="flex-1 px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
          <div className="mx-auto max-w-7xl">{children}</div>
        </main>
      </div>
    </div>
  );
}

function SidebarFooter({ user }: { user: CurrentUser }) {
  const t = useTranslations("roles");
  return (
    <div className="mt-6 flex items-center gap-3 rounded-xl border border-panel-border bg-panel-foreground/5 p-3 text-sm">
      <span
        aria-hidden="true"
        className="bg-brand-gradient grid size-9 shrink-0 place-items-center rounded-full font-semibold text-white"
      >
        {(user.display_name || "?").trim().charAt(0).toUpperCase()}
      </span>
      <span className="grid min-w-0">
        <span className="truncate font-semibold">
          {user.display_name || formatIndianPhone(user.phone)}
        </span>
        <span className="truncate text-panel-muted-foreground">
          {user.roles
            .filter((assignment) => assignment.role !== "citizen")
            .map((assignment) => t(assignment.role))
            .join(", ")}
        </span>
      </span>
    </div>
  );
}

function SidebarSkeleton() {
  return (
    <div className="grid gap-2 opacity-20">
      <Skeleton className="h-9" />
      <Skeleton className="h-9" />
      <Skeleton className="h-9" />
    </div>
  );
}

/**
 * Admin console chrome: sidebar on large screens, a disclosure menu on
 * small ones. Navigation is filtered by the user's permissions.
 *
 * The shell always renders `children`, even before the session is known.
 * Access checks live in each page (RequireAdminAccess) instead of here: a
 * layout that swaps its children for a fallback drops the page segment
 * from the prerender, and Next can then no longer validate that
 * navigations into it are instant (instant-unrendered-segment). The page
 * guards render the same loading state, so nothing changes for users.
 */
export function AdminShell({ children }: { children: ReactNode }) {
  const { status, user } = useSession();
  const admin = user && canUseAdmin(user) ? user : null;

  return (
    <Frame
      sidebar={
        admin ? (
          <>
            <AdminNav user={admin} tone="dark" />
            <SidebarFooter user={admin} />
          </>
        ) : status === "unknown" ? (
          <SidebarSkeleton />
        ) : null
      }
      mobileNav={
        admin
          ? (close) => <AdminNav user={admin} onNavigate={close} />
          : undefined
      }
    >
      {children}
    </Frame>
  );
}
