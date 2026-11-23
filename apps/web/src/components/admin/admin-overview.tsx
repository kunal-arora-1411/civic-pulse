"use client";

import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useSession } from "@/lib/auth/use-session";
import { ADMIN_NAV, type AdminNavKey, visibleNavItems } from "./nav-items";
import { PageHeader } from "./page-header";

export function AdminOverview() {
  const t = useTranslations("admin");
  const { user } = useSession();
  if (!user) return null;

  const sections = visibleNavItems(user).filter(
    (item) => item.key !== ADMIN_NAV[0]?.key,
  );
  const descriptions: Partial<Record<AdminNavKey, string>> = {
    issues: t("overview.issuesBody"),
    users: t("overview.usersBody"),
    audit: t("overview.auditBody"),
  };
  return (
    <div className="grid gap-8 motion-safe:animate-rise">
      <PageHeader
        title={
          user.display_name
            ? t("overview.greeting", { name: user.display_name })
            : t("overview.title")
        }
        description={t("overview.description")}
      />

      {sections.length > 0 ? (
        <section aria-labelledby="overview-sections" className="grid gap-3">
          <h2
            id="overview-sections"
            className="text-sm font-semibold tracking-wide text-muted-foreground uppercase"
          >
            {t("overview.manage")}
          </h2>
          <ul className="grid gap-4 sm:grid-cols-2">
            {sections.map((item) => {
              const Icon = item.icon;
              return (
                <li key={item.key}>
                  <Link
                    href={item.href}
                    className="group flex h-full items-start gap-4 rounded-xl border border-border bg-card p-5 shadow-card transition-shadow hover:shadow-raised"
                  >
                    <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary-soft-foreground">
                      <Icon aria-hidden="true" className="size-5" />
                    </span>
                    <span className="grid flex-1 gap-1">
                      <span className="font-semibold">
                        {t(`nav.${item.key}`)}
                      </span>
                      <span className="text-sm text-muted-foreground">
                        {descriptions[item.key]}
                      </span>
                    </span>
                    <ArrowRight
                      aria-hidden="true"
                      className="mt-1 size-5 text-muted-foreground transition-transform group-hover:translate-x-0.5 rtl:rotate-180"
                    />
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
