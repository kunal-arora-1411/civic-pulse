import { useTranslations } from "next-intl";
import { AccountMenu } from "@/components/account-menu";
import { Logo } from "@/components/brand/logo";
import { LanguageSwitcher } from "@/components/language-switcher";
import { ThemeSwitcher } from "@/components/theme-switcher";
import { Link } from "@/i18n/navigation";

export default function CitizenLayout({ children }: LayoutProps<"/[locale]">) {
  const t = useTranslations();
  return (
    <div className="flex flex-1 flex-col">
      <header className="sticky top-0 z-30 border-b border-border/70 bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
        <div className="mx-auto flex h-16 max-w-[1200px] items-center justify-between gap-3 px-5 sm:px-8">
          <Link href="/" className="rounded-lg">
            <Logo />
          </Link>
          <div className="flex items-center gap-2 sm:gap-3">
            <ThemeSwitcher className="hidden sm:flex" />
            <LanguageSwitcher />
            <AccountMenu />
          </div>
        </div>
      </header>
      {children}
      <footer className="border-t border-border/70">
        <p className="mx-auto max-w-[1200px] px-5 py-6 text-sm text-muted-foreground sm:px-8">
          {t("citizen.footer")}
        </p>
      </footer>
    </div>
  );
}
