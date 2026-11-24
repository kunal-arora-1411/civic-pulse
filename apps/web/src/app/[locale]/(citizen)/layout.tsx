import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { AccountMenu } from "@/components/account-menu";
import { Logo } from "@/components/brand/logo";
import { LanguageSwitcher } from "@/components/language-switcher";
import { buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

/*
 * No usePathname here for active nav states: it would push every citizen
 * page out of the static shell (see CLAUDE.md, "Things that bite").
 */
export default function CitizenLayout({ children }: LayoutProps<"/[locale]">) {
  const t = useTranslations();
  return (
    <div className="flex flex-1 flex-col">
      <header className="sticky top-0 z-30 border-b border-border/60 bg-background/80 backdrop-blur-md supports-backdrop-filter:bg-background/65">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
          <div className="flex items-center gap-8">
            <Link href="/" className="rounded-lg">
              <Logo />
            </Link>
            <nav className="hidden md:block">
              <ul className="flex items-center gap-1 text-sm">
                <li>
                  <Link
                    href="/reports"
                    className="rounded-md px-3 py-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    {t("citizen.myReports")}
                  </Link>
                </li>
              </ul>
            </nav>
          </div>
          <div className="flex items-center gap-2 sm:gap-3">
            <LanguageSwitcher />
            <AccountMenu />
            <Link
              href="/report"
              className={cn(
                buttonVariants({ variant: "ink", size: "sm" }),
                "hidden sm:inline-flex",
              )}
            >
              {t("citizen.reportCta")}
              <ArrowRight aria-hidden="true" className="rtl:rotate-180" />
            </Link>
          </div>
        </div>
      </header>
      {children}
      <footer className="relative mt-auto border-t border-border/60">
        <div
          aria-hidden="true"
          className="bg-brand-gradient absolute inset-x-0 -top-px h-px opacity-70"
        />
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-8 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="grid gap-1.5">
            <Logo className="[&_svg]:size-6 [&>span:last-child]:text-base" />
            <p className="text-sm text-muted-foreground">
              {t("citizen.footer")}
            </p>
          </div>
          <p className="eyebrow">{t("common.tagline")}</p>
        </div>
      </footer>
    </div>
  );
}
