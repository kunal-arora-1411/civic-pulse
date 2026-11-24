import { BellRing, EyeOff, Smartphone } from "lucide-react";
import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { LoginFlow } from "@/components/auth/login-flow";
import { TenantName } from "@/components/auth/tenant-name";
import { Logo } from "@/components/brand/logo";
import { LanguageSwitcher } from "@/components/language-switcher";
import { ThemeSwitcher } from "@/components/theme-switcher";
import { Card } from "@/components/ui/card";
import { Link } from "@/i18n/navigation";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("login");
  return { title: t("metaTitle") };
}

export default function LoginPage() {
  const t = useTranslations("login");
  const points = [
    { icon: Smartphone, text: t("brandPoint1") },
    { icon: BellRing, text: t("brandPoint2") },
    { icon: EyeOff, text: t("brandPoint3") },
  ];

  return (
    <div className="grid flex-1 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <aside className="relative hidden overflow-hidden bg-primary text-primary-foreground lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div
          aria-hidden="true"
          className="bg-survey-grid absolute inset-0 opacity-60 [--grid-dot:color-mix(in_oklch,var(--primary-foreground)_18%,transparent)]"
        />
        <div
          aria-hidden="true"
          className="absolute -end-24 -bottom-24 size-96 rounded-full border-[28px] border-accent/30"
        />
        <Link href="/" className="relative w-fit rounded-lg">
          <Logo className="[&_rect]:fill-primary-foreground/15" />
        </Link>
        <div className="relative grid max-w-md gap-6">
          <p className="font-display text-4xl font-semibold leading-tight">
            {t("brandHeading")}
          </p>
          <p className="text-lg opacity-90">{t("brandBody")}</p>
          <ul className="grid gap-3">
            {points.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3">
                <span className="grid size-8 place-items-center rounded-full bg-primary-foreground/15">
                  <Icon aria-hidden="true" className="size-4" />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-sm opacity-80">{t("privacy")}</p>
      </aside>

      <div className="bg-survey-grid flex flex-col">
        <header className="flex items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <Link href="/" className="rounded-lg lg:invisible">
            <Logo />
          </Link>
          <div className="flex items-center gap-2">
            <ThemeSwitcher />
            <LanguageSwitcher />
          </div>
        </header>
        <main
          id="main"
          className="flex flex-1 items-start justify-center px-4 pt-6 pb-16 sm:items-center sm:px-6"
        >
          <div className="grid w-full max-w-md gap-4 motion-safe:animate-rise">
            <TenantName />
            <Card className="p-6 sm:p-8">
              <LoginFlow />
            </Card>
            <p className="px-2 text-center text-sm text-muted-foreground lg:hidden">
              {t("privacy")}
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}
