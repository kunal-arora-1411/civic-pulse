"use client";

import { Languages } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useId, useTransition } from "react";
import { Select } from "@/components/ui/select";
import { type AppLocale, localeNames, locales } from "@/i18n/routing";
import { switchLocale } from "@/i18n/switch-locale";
import { session, updateMe } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Works without signing in (PRD §9.1). The choice is stored in the
 * NEXT_LOCALE cookie and the page reloads in the new language (see
 * switchLocale for why it isn't a soft navigation). Signed-in users also
 * get it saved to their profile, so SMS and notifications follow the same
 * language; that save is best effort and never blocks the switch.
 */
export function LanguageSwitcher({ className }: { className?: string }) {
  const t = useTranslations("language");
  const locale = useLocale();
  const [pending, startTransition] = useTransition();
  const id = useId();

  return (
    <div className={cn("flex items-center gap-1.5", className)}>
      <label htmlFor={id} className="text-muted-foreground">
        <Languages aria-hidden="true" className="size-4" />
        <span className="sr-only">{t("label")}</span>
      </label>
      <Select
        id={id}
        value={locale}
        disabled={pending}
        aria-busy={pending || undefined}
        className="[&_select]:h-9 [&_select]:w-auto [&_select]:text-sm"
        onChange={(event) => {
          const next = event.target.value as AppLocale;
          startTransition(async () => {
            if (session.getSnapshot().status === "authenticated") {
              await updateMe({ locale: next }).catch(() => undefined);
            }
            switchLocale(next);
          });
        }}
      >
        {locales.map((value) => (
          <option key={value} value={value} lang={value}>
            {localeNames[value]}
          </option>
        ))}
      </Select>
      <output className="sr-only">{pending ? t("switching") : ""}</output>
    </div>
  );
}
