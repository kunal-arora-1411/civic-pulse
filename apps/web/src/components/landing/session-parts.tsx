"use client";

import { ArrowRight, LayoutDashboard } from "lucide-react";
import { useTranslations } from "next-intl";
import { AccountMenu } from "@/components/account-menu";
import { useMyReports } from "@/components/citizen/my-reports-screen";
import {
  ReportCard,
  ReportCardSkeleton,
} from "@/components/citizen/report-card";
import { Link } from "@/i18n/navigation";
import { canUseAdmin } from "@/lib/auth/access";
import { useSession } from "@/lib/auth/use-session";
import { cn } from "@/lib/utils";
import { Container, mutedSmall } from "./primitives";
import { buttonBase, buttonTone } from "./styles";

/**
 * The navbar's right-hand side. The session lives only in browser memory,
 * so this renders a same-sized placeholder until it's known.
 */
export function HeaderActions() {
  const t = useTranslations("landing.nav");
  const { status } = useSession();
  const small = "h-9 rounded-lg px-3.5 text-sm";

  return (
    <div className="flex items-center gap-2">
      {status === "unknown" ? (
        <span
          aria-hidden="true"
          className="hidden h-9 w-20 rounded-lg bg-lp-wash sm:block"
        />
      ) : status === "authenticated" ? (
        <AccountMenu />
      ) : (
        <Link
          href="/login"
          className={cn(
            buttonBase,
            buttonTone.secondary,
            small,
            "hidden sm:inline-flex",
          )}
        >
          {t("signIn")}
        </Link>
      )}
      <Link
        href="/report"
        className={cn(buttonBase, buttonTone.primary, small)}
      >
        {t("report")}
      </Link>
    </div>
  );
}

/**
 * Signed-in citizens get their latest reports right under the hero, so the
 * landing page still works as their home. Nobody else sees anything here.
 */
export function RecentReportsStrip() {
  const { status, user } = useSession();
  if (status !== "authenticated" || !user) return null;
  return <RecentReports showStaff={canUseAdmin(user)} />;
}

function RecentReports({ showStaff }: { showStaff: boolean }) {
  const t = useTranslations("landing.recent");
  const query = useMyReports(3);
  const items = query.data?.pages[0]?.items ?? [];

  return (
    <section
      aria-labelledby="lp-recent"
      className="border-b border-lp-hair bg-lp-wash/60 py-14"
    >
      <Container className="grid gap-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <h2
            id="lp-recent"
            className="max-w-2xl text-2xl font-medium tracking-[-0.03em] text-lp-ink sm:text-[28px]"
          >
            {t.rich("title", { muted: mutedSmall })}
          </h2>
          <div className="flex flex-wrap gap-2">
            {showStaff ? (
              <Link
                href="/admin"
                className={cn(
                  buttonBase,
                  buttonTone.secondary,
                  "h-10 px-4 text-sm",
                )}
              >
                <LayoutDashboard aria-hidden="true" className="size-4" />
                {t("staff")}
              </Link>
            ) : null}
            <Link
              href="/reports"
              className={cn(
                buttonBase,
                buttonTone.secondary,
                "h-10 px-4 text-sm",
              )}
            >
              {t("all")}
              <ArrowRight
                aria-hidden="true"
                className="size-4 rtl:rotate-180"
              />
            </Link>
          </div>
        </div>
        {query.isPending ? (
          <div className="grid gap-3">
            <output className="sr-only">{t("loading")}</output>
            <ReportCardSkeleton />
          </div>
        ) : items.length > 0 ? (
          <ul className="grid gap-3 md:grid-cols-3">
            {items.map((report) => (
              <li key={report.id}>
                <ReportCard report={report} />
              </li>
            ))}
          </ul>
        ) : query.isSuccess ? (
          <p className="text-lp-mute-2">{t("empty")}</p>
        ) : null}
      </Container>
    </section>
  );
}
