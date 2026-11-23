"use client";

import { Languages } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useId, useTransition } from "react";
import { Select } from "@/components/ui/select";
import { usePathname, useRouter } from "@/i18n/navigation";
import { type AppLocale, localeNames, locales } from "@/i18n/routing";
import { cn } from "@/lib/utils";

/**
 * Works without signing in (PRD §9.1). The choice is stored in the
 * NEXT_LOCALE cookie by next-intl's router.
 *
 * Changing the locale changes the root `[locale]` segment, so Next performs
 * a full document navigation rather than a soft one. That is intentional:
 * every server-rendered string has to be re-rendered anyway.
 */
export function LanguageSwitcher({
  className,
  onChange,
}: {
  className?: string;
  /** Called with the new locale before navigating, e.g. to persist it. */
  onChange?: (locale: AppLocale) => void | Promise<void>;
}) {
  const t = useTranslations("language");
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
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
            await onChange?.(next);
            router.replace(pathname, { locale: next });
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
