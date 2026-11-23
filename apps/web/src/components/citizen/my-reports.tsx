"use client";

import { ArrowRight, LayoutDashboard, LogIn } from "lucide-react";
import { useTranslations } from "next-intl";
import { buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Link } from "@/i18n/navigation";
import type { CurrentUser } from "@/lib/api";
import { canUseAdmin } from "@/lib/auth/access";
import { useSession } from "@/lib/auth/use-session";
import { NoReports, useMyReports } from "./my-reports-screen";
import { ReportCard, ReportCardSkeleton } from "./report-card";

const PREVIEW = 3;

function RecentReports({ user }: { user: CurrentUser }) {
  const t = useTranslations("citizen");
  const query = useMyReports(PREVIEW);
  const items = query.data?.pages[0]?.items ?? [];
  const total = query.data?.pages[0]?.total ?? 0;

  return (
    <>
      {query.isPending ? (
        <div className="grid gap-3">
          <output className="sr-only">{t("loadingReports")}</output>
          <ReportCardSkeleton />
        </div>
      ) : items.length > 0 ? (
        <ul className="grid gap-3">
          {items.map((report) => (
            <li key={report.id}>
              <ReportCard report={report} />
            </li>
          ))}
        </ul>
      ) : query.isSuccess ? (
        <NoReports />
      ) : null}
      {total > PREVIEW ? (
        <Link
          href="/reports"
          className={buttonVariants({
            variant: "outline",
            className: "justify-self-start",
          })}
        >
          {t("seeAllReports", { count: total })}
          <ArrowRight aria-hidden="true" className="rtl:rotate-180" />
        </Link>
      ) : null}
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
  );
}

/** The home page's "My reports" panel: the latest few, or a sign-in prompt. */
export function MyReports() {
  const t = useTranslations("citizen");
  const { status, user } = useSession();

  return (
    <section aria-labelledby="my-reports" className="grid gap-4">
      <h2 id="my-reports" className="text-2xl font-semibold">
        {t("myReports")}
      </h2>

      {status === "unknown" ? (
        <div className="grid gap-3">
          <output className="sr-only">{t("loadingReports")}</output>
          <ReportCardSkeleton />
        </div>
      ) : status === "anonymous" || !user ? (
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
        <RecentReports user={user} />
      )}
    </section>
  );
}
