import { defineRouting } from "next-intl/routing";

export const locales = ["en", "hi"] as const;
export type AppLocale = (typeof locales)[number];

/** Each language's name written in that language, for the switcher. */
export const localeNames: Record<AppLocale, string> = {
  en: "English",
  hi: "हिन्दी",
};

/*
 * URLs never carry a locale prefix: the proxy reads the NEXT_LOCALE cookie
 * (falling back to Accept-Language) and rewrites `/admin` to `/hi/admin`
 * internally. The locale still reaches the app as the root `[locale]`
 * param, which lets every page prerender once per language. Reading the
 * cookie during render instead would make the root layout depend on
 * request data, and Cache Components would then refuse to build a static
 * shell for any route.
 */
export const localeCookie = {
  name: "NEXT_LOCALE",
  maxAge: 60 * 60 * 24 * 365,
  sameSite: "lax",
} as const;

export const routing = defineRouting({
  locales,
  defaultLocale: "en",
  localePrefix: "never",
  localeCookie,
  alternateLinks: false,
});
