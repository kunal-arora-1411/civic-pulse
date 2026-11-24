import { useTranslations } from "next-intl";
import { AccountMenu } from "@/components/account-menu";
import { Logo } from "@/components/brand/logo";
import { LanguageSwitcher } from "@/components/language-switcher";
import { Link } from "@/i18n/navigation";

export default function FieldLayout({
  children,
}: LayoutProps<"/[locale]/field">) {
  const t = useTranslations("field");
  return (
    <div className="flex flex-1 flex-col bg-muted/60">
      <header className="sticky top-0 z-30 bg-panel text-panel-foreground">
        <div className="mx-auto flex h-14 max-w-2xl items-center justify-between gap-3 px-4">
          <Link href="/field" className="flex items-center gap-2 rounded-lg">
            <Logo className="[&>span:last-child]:hidden sm:[&>span:last-child]:inline" />
            <span className="eyebrow rounded-full border border-panel-border px-2 py-0.5 text-panel-muted-foreground">
              {t("badge")}
            </span>
          </Link>
          <div className="flex items-center gap-2">
            <LanguageSwitcher />
            <AccountMenu />
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-2xl flex-1 px-4 py-6">
        {children}
      </main>
    </div>
  );
}
