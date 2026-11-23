"use client";

import { useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";
import type { CurrentUser } from "@/lib/api";
import { cn } from "@/lib/utils";
import { isActive, visibleNavItems } from "./nav-items";

export function AdminNav({
  user,
  onNavigate,
  className,
}: {
  user: CurrentUser;
  onNavigate?: () => void;
  className?: string;
}) {
  const t = useTranslations("admin.nav");
  const pathname = usePathname();
  const items = visibleNavItems(user);

  return (
    <nav aria-label={t("label")} className={className}>
      <ul className="grid gap-1">
        {items.map((item) => {
          const active = isActive(item, pathname);
          const Icon = item.icon;
          return (
            <li key={item.key}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                onClick={onNavigate}
                className={cn(
                  "relative flex items-center gap-3 rounded-lg px-3 py-2 text-[0.9375rem] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                  active &&
                    "bg-primary-soft text-primary-soft-foreground hover:bg-primary-soft hover:text-primary-soft-foreground",
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
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
