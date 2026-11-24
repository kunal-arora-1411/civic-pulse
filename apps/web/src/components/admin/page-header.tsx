import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { type AdminNavKey, navGroupOf } from "./nav-items";

/**
 * Page title block in the marketing site's style: an optional mono
 * eyebrow, a tight display heading, and a muted description.
 */
export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
  section,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
  /** Console section; its sidebar group becomes the eyebrow. */
  section?: AdminNavKey;
}) {
  const t = useTranslations("admin.groups");
  const label = eyebrow ?? (section ? t(navGroupOf(section)) : null);
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="grid gap-2">
        {label ? <p className="eyebrow">{label}</p> : null}
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          {title}
        </h1>
        {description ? (
          <p className="max-w-2xl text-[0.9375rem] text-muted-foreground sm:text-base">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? (
        <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>
      ) : null}
    </div>
  );
}
