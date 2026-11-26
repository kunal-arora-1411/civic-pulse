"use client";

import { useLocale, useTranslations } from "next-intl";
import { useId, useTransition } from "react";
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
 *
 * With two languages a segmented toggle shows both choices at once and
 * themes cleanly, unlike a native <select> whose open list the browser
 * draws. They're native radios, so arrow keys move between them.
 */
export function LanguageSwitcher({ className }: { className?: string }) {
  const t = useTranslations("language");
  const locale = useLocale();
  const [pending, startTransition] = useTransition();
  const name = useId();

  const choose = (next: AppLocale) => {
    if (next === locale || pending) return;
    startTransition(async () => {
      if (session.getSnapshot().status === "authenticated") {
        await updateMe({ locale: next }).catch(() => undefined);
      }
      switchLocale(next);
    });
  };

  return (
    <div className={cn("flex items-center", className)}>
      <fieldset
        aria-busy={pending || undefined}
        className="m-0 flex h-9 min-w-0 items-center gap-0.5 rounded-full border border-border bg-muted p-0.5"
      >
        <legend className="sr-only">{t("label")}</legend>
        {locales.map((value) => (
          <label
            key={value}
            lang={value}
            className={cn(
              "flex h-full cursor-pointer items-center rounded-full px-3 text-sm font-medium text-muted-foreground transition-colors select-none hover:text-foreground",
              "has-checked:bg-card has-checked:text-foreground has-checked:shadow-card",
              "has-focus-visible:outline-2 has-focus-visible:outline-offset-1 has-focus-visible:outline-ring",
              "has-disabled:cursor-default",
            )}
          >
            <input
              type="radio"
              name={name}
              value={value}
              checked={value === locale}
              disabled={pending && value !== locale}
              onChange={() => choose(value)}
              className="sr-only"
            />
            {localeNames[value]}
          </label>
        ))}
      </fieldset>
      <output className="sr-only">{pending ? t("switching") : ""}</output>
    </div>
  );
}
