import type { Metadata, Viewport } from "next";
import { notFound } from "next/navigation";
import { hasLocale, NextIntlClientProvider } from "next-intl";
import { getLocale, getTranslations } from "next-intl/server";
import { AppProviders } from "@/components/providers";
import { themeScript } from "@/components/theme-switcher";
import { locales, routing } from "@/i18n/routing";
import { fontVariables } from "@/lib/fonts";
import { cn } from "@/lib/utils";
import "../globals.css";

// Cache Components needs at least one value per root param to build.
export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("metadata");
  return {
    title: { default: "CivicPulse", template: "%s · CivicPulse" },
    description: t("description"),
    applicationName: "CivicPulse",
  };
}

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#faf9f5" },
    { media: "(prefers-color-scheme: dark)", color: "#121b21" },
  ],
};

export default async function LocaleLayout({
  children,
}: LayoutProps<"/[locale]">) {
  const locale = await getLocale();
  if (!hasLocale(routing.locales, locale)) notFound();
  const t = await getTranslations("common");

  return (
    <html
      lang={locale}
      className={cn(fontVariables, "h-full")}
      // The theme script below may set data-theme before React hydrates.
      suppressHydrationWarning
    >
      <head>
        <script
          // biome-ignore lint/security/noDangerouslySetInnerHtml: a fixed, first-party script that applies the saved theme before first paint
          dangerouslySetInnerHTML={{ __html: themeScript }}
        />
      </head>
      <body className="flex min-h-full flex-col">
        <a
          href="#main"
          className="sr-only z-50 rounded-lg bg-primary px-4 py-2 font-semibold text-primary-foreground focus:not-sr-only focus:fixed focus:start-4 focus:top-4"
        >
          {t("skipToContent")}
        </a>
        <NextIntlClientProvider>
          <AppProviders>{children}</AppProviders>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
