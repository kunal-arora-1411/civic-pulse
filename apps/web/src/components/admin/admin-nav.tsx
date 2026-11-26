"use client";

import { useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";
import type { CurrentUser } from "@/lib/api";
import { cn } from "@/lib/utils";
import { isActive, visibleNavItems } from "./nav-items";
import { useOpenReviewCount } from "./review/use-open-review-count";

export function AdminNav({
  user,
  onNavigate,
  className,
  tone = "light",
}: {
  user: CurrentUser;
  onNavigate?: () => void;
  className?: string;
  /** `dark` for the ink sidebar, `light` for the mobile menu. */
  tone?: "light" | "dark";
}) {
  const t = useTranslations("admin.nav");
  const pathname = usePathname();
  const items = visibleNavItems(user);
  const openReviews = useOpenReviewCount();

  const tGroups = useTranslations("admin.groups");
  const groups = (["operations", "configuration", "governance"] as const)
    .map((group) => ({
      group,
      items: items.filter((item) => item.group === group),
    }))
    .filter(({ items: groupItems }) => groupItems.length > 0);

  return (
    <nav aria-label={t("label")} className={className}>
      <div className="grid gap-5">
        {groups.map(({ group, items: groupItems }) => (
          <div key={group} className="grid gap-1.5">
            <p
              className={cn(
                "eyebrow px-3",
                tone === "dark" && "text-panel-muted-foreground/70",
              )}
            >
              {tGroups(group)}
            </p>
            <ul className="grid gap-0.5">
              {groupItems.map((item) => {
                const active = isActive(item, pathname);
                const Icon = item.icon;
                return (
                  <li key={item.key}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      onClick={onNavigate}
                      className={cn(
                        "relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                        tone === "dark"
                          ? "text-panel-muted-foreground hover:bg-panel-foreground/5 hover:text-panel-foreground"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground",
                        active &&
                          (tone === "dark"
                            ? "bg-panel-foreground/10 text-panel-foreground hover:bg-panel-foreground/10"
                            : "bg-primary-soft text-primary-soft-foreground hover:bg-primary-soft hover:text-primary-soft-foreground"),
                      )}
                    >
                      {active ? (
                        <span
                          aria-hidden="true"
                          className="absolute inset-y-1.5 -start-3 w-1 rounded-e-full bg-accent"
                        />
                      ) : null}
                      <Icon aria-hidden="true" className="size-[1.125rem]" />
                      {t(item.key)}
                      {item.badge === "openReviews" && openReviews > 0 ? (
                        <span className="ms-auto rounded-full bg-accent px-2 text-xs leading-5 font-semibold text-accent-foreground tabular-nums">
                          <span aria-hidden="true">{openReviews}</span>
                          <span className="sr-only">
                            {t("openReviews", { count: openReviews })}
                          </span>
                        </span>
                      ) : null}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </nav>
  );
}
