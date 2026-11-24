"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { useFormatter, useNow, useTranslations } from "next-intl";
import { BrandArcs } from "@/components/brand/brand-arcs";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Stat } from "@/components/ui/stat";
import { Link } from "@/i18n/navigation";
import { type IssueStatus, listIssues } from "@/lib/api";
import { hasPermission } from "@/lib/auth/access";
import { useSession } from "@/lib/auth/use-session";
import { cn } from "@/lib/utils";
import { ADMIN_NAV, type AdminNavKey, visibleNavItems } from "./nav-items";
import { useOpenReviewCount } from "./review/use-open-review-count";

const KPI_STATUSES = {
  open: [
    "reported",
    "under_review",
    "verified",
    "assigned",
    "in_progress",
    "pending_verification",
    "reopened",
  ],
  untriaged: ["reported", "under_review"],
  inProgress: ["assigned", "in_progress"],
  resolved: ["resolved", "closed"],
} as const satisfies Record<string, readonly IssueStatus[]>;

type KpiKey = keyof typeof KPI_STATUSES;

/** One count per tile, using the list endpoint's total with limit 1. */
function useIssueCount(key: KpiKey, enabled: boolean) {
  return useQuery({
    queryKey: ["issues", "overview-count", key],
    queryFn: ({ signal }) =>
      listIssues({ status: KPI_STATUSES[key], limit: 1 }, signal),
    enabled,
    select: (page) => page.total,
    staleTime: 60_000,
  });
}

function KpiTile({
  kpi,
  enabled,
  tone,
}: {
  kpi: KpiKey;
  enabled: boolean;
  tone?: "neutral" | "primary" | "warning";
}) {
  const t = useTranslations("admin.overview.kpi");
  const format = useFormatter();
  const query = useIssueCount(kpi, enabled);
  return (
    <Stat
      label={t(`${kpi}Label`)}
      tone={tone}
      value={
        query.isSuccess ? (
          format.number(query.data)
        ) : query.isError ? (
          "—"
        ) : (
          <Skeleton className="h-10 w-20" />
        )
      }
      hint={t(`${kpi}Hint`)}
    />
  );
}

/** Rendered only once the session is known, so never during prerender. */
function Today() {
  const format = useFormatter();
  const now = useNow();
  return (
    <p className="eyebrow text-panel-muted-foreground">
      {format.dateTime(now, { dateStyle: "full" })}
    </p>
  );
}

export function AdminOverview() {
  const t = useTranslations("admin");
  const format = useFormatter();
  const { user } = useSession();
  const openReviews = useOpenReviewCount();
  if (!user) return null;

  const canReadIssues = hasPermission(user, "issue:read");
  const sections = visibleNavItems(user).filter(
    (item) => item.key !== ADMIN_NAV[0]?.key,
  );
  const descriptions: Partial<Record<AdminNavKey, string>> = {
    issues: t("overview.issuesBody"),
    map: t("overview.mapBody"),
    categories: t("overview.categoriesBody"),
    users: t("overview.usersBody"),
    audit: t("overview.auditBody"),
  };

  return (
    <div className="grid gap-10 motion-safe:animate-rise">
      <section className="relative isolate overflow-hidden rounded-3xl bg-panel px-6 py-8 text-panel-foreground sm:px-10 sm:py-12">
        <BrandArcs className="absolute end-0 bottom-0 -z-10 h-full w-2/3 opacity-90 sm:w-1/2" />
        <div
          aria-hidden="true"
          className="absolute inset-0 -z-10 bg-linear-to-r from-panel via-panel/70 to-transparent rtl:bg-linear-to-l"
        />
        <div className="grid max-w-xl gap-4">
          <Today />
          <h1 className="text-3xl font-semibold tracking-tight sm:text-5xl">
            {user.display_name
              ? t("overview.greeting", { name: user.display_name })
              : t("overview.title")}
          </h1>
          <p className="text-panel-muted-foreground sm:text-lg">
            {t("overview.description")}
          </p>
          {canReadIssues ? (
            <div className="mt-2 flex flex-wrap gap-2">
              <Link
                href="/admin/issues"
                className={cn(
                  buttonVariants({ size: "md" }),
                  "bg-panel-foreground text-panel hover:bg-panel-foreground/90",
                )}
              >
                {t("nav.issues")}
                <ArrowRight aria-hidden="true" className="rtl:rotate-180" />
              </Link>
              {openReviews > 0 ? (
                <Link
                  href="/admin/review"
                  className={cn(
                    buttonVariants({ variant: "ghost", size: "md" }),
                    "border border-panel-border text-panel-foreground hover:bg-panel-foreground/10",
                  )}
                >
                  {t("nav.review")}
                  <span className="rounded-full bg-accent px-2 text-xs leading-5 font-semibold text-accent-foreground tabular-nums">
                    {format.number(openReviews)}
                  </span>
                </Link>
              ) : null}
            </div>
          ) : null}
        </div>
      </section>

      {canReadIssues ? (
        <section aria-labelledby="overview-kpis" className="grid gap-4">
          <h2 id="overview-kpis" className="eyebrow">
            {t("overview.kpi.heading")}
          </h2>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiTile kpi="open" enabled={canReadIssues} />
            <KpiTile kpi="untriaged" enabled={canReadIssues} tone="warning" />
            <KpiTile kpi="inProgress" enabled={canReadIssues} />
            <KpiTile kpi="resolved" enabled={canReadIssues} tone="primary" />
          </div>
        </section>
      ) : null}

      {sections.length > 0 ? (
        <section aria-labelledby="overview-sections" className="grid gap-4">
          <h2 id="overview-sections" className="eyebrow">
            {t("overview.manage")}
          </h2>
          <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {sections.map((item, index) => {
              const Icon = item.icon;
              return (
                <li key={item.key}>
                  <Link
                    href={item.href}
                    className="group relative flex h-full flex-col gap-6 rounded-2xl border border-border bg-card p-5 shadow-card transition-[box-shadow,border-color] hover:border-input/40 hover:shadow-raised"
                  >
                    <span className="flex items-start justify-between">
                      <span className="grid size-10 place-items-center rounded-xl bg-muted text-foreground transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                        <Icon aria-hidden="true" className="size-5" />
                      </span>
                      <span
                        aria-hidden="true"
                        className="font-mono text-xs text-muted-foreground"
                      >
                        {String(index + 1).padStart(2, "0")}
                      </span>
                    </span>
                    <span className="grid gap-1">
                      <span className="flex items-center gap-1.5 font-semibold tracking-tight">
                        {t(`nav.${item.key}`)}
                        <ArrowUpRight
                          aria-hidden="true"
                          className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5 rtl:-scale-x-100"
                        />
                      </span>
                      {descriptions[item.key] ? (
                        <span className="text-sm text-muted-foreground">
                          {descriptions[item.key]}
                        </span>
                      ) : null}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
