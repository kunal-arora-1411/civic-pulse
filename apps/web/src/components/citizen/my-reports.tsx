"use client";

import { ArrowRight, Inbox, LayoutDashboard, LogIn } from "lucide-react";
import { useTranslations } from "next-intl";
import { buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Link } from "@/i18n/navigation";
import { canUseAdmin } from "@/lib/auth/access";
import { useSession } from "@/lib/auth/use-session";

/** "My reports" placeholder. The list itself arrives with Phase 1. */
export function MyReports() {
  const t = useTranslations("citizen");
  const { status, user } = useSession();

  return (
    <section aria-labelledby="my-reports" className="grid gap-4">
      <div className="flex items-end justify-between gap-4">
        <h2 id="my-reports" className="text-2xl font-semibold">
          {t("myReports")}
        </h2>
      </div>

      {status === "unknown" ? (
        <Card className="p-6">
          <output className="sr-only">{t("loadingReports")}</output>
          <div className="grid gap-3">
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        </Card>
      ) : status === "anonymous" ? (
        <Card className="flex flex-col items-start gap-4 p-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex gap-4">
            <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-secondary text-secondary-foreground">
              <LogIn aria-hidden="true" className="size-5" />
            </span>
            <div className="grid gap-1">
              <p className="font-semibold">{t("signInToSeeTitle")}</p>
              <p className="text-muted-foreground">{t("signInToSeeBody")}</p>
            </div>
          </div>
          <Link
            href="/login"
            className={buttonVariants({ variant: "outline" })}
          >
            {t("signIn")}
          </Link>
        </Card>
      ) : (
        <>
          <Card className="flex gap-4 p-6">
            <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-secondary text-secondary-foreground">
              <Inbox aria-hidden="true" className="size-5" />
            </span>
            <div className="grid gap-1">
              <p className="font-semibold">{t("noReportsTitle")}</p>
              <p className="text-muted-foreground">{t("noReportsBody")}</p>
            </div>
          </Card>
          {canUseAdmin(user) ? (
            <Link
              href="/admin"
              className="group flex items-center justify-between gap-3 rounded-xl border border-primary/25 bg-primary-soft px-5 py-4 font-semibold text-primary-soft-foreground"
            >
              <span className="flex items-center gap-3">
                <LayoutDashboard aria-hidden="true" className="size-5" />
                {t("staffShortcut")}
              </span>
              <ArrowRight
                aria-hidden="true"
                className="size-5 transition-transform group-hover:translate-x-0.5 rtl:rotate-180"
              />
            </Link>
          ) : null}
        </>
      )}
    </section>
  );
}
