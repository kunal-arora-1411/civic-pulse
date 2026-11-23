import { locale as rootLocale } from "next/root-params";
import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";
import { routing } from "./routing";

export const TIME_ZONE = "Asia/Kolkata";

export default getRequestConfig(async () => {
  // `next/root-params` resolves the `[locale]` segment without touching
  // headers or cookies, so this stays prerenderable.
  const requested = await rootLocale();
  const locale = hasLocale(routing.locales, requested)
    ? requested
    : routing.defaultLocale;

  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
    // Pin the zone so server and browser format dates identically.
    timeZone: TIME_ZONE,
  };
});
