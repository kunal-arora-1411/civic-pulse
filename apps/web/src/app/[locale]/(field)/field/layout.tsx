import { useTranslations } from "next-intl";
import { AccountMenu } from "@/components/account-menu";
import { RequireFieldAccess } from "@/components/auth/guards";
import { Logo } from "@/components/brand/logo";
import { LanguageSwitcher } from "@/components/language-switcher";
import { Badge } from "@/components/ui/badge";
import { Link } from "@/i18n/navigation";

export default function FieldLayout({
  children,
}: LayoutProps<"/[locale]/field">) {
  const t = useTranslations("field");
  return (
    <div className="flex flex-1 flex-col bg-muted/40">
      <header className="sticky top-0 z-30 border-b border-border bg-card">
        <div className="mx-auto flex h-14 max-w-2xl items-center justify-between gap-3 px-4">
          <Link href="/field" className="flex items-center gap-2 rounded-lg">
            <Logo className="[&>span:last-child]:hidden sm:[&>span:last-child]:inline" />
            <Badge variant="primary">{t("badge")}</Badge>
          </Link>
          <div className="flex items-center gap-2">
            <LanguageSwitcher />
            <AccountMenu />
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-2xl flex-1 px-4 py-6">
        <RequireFieldAccess>{children}</RequireFieldAccess>
      </main>
    </div>
  );
}
