import { BellRing, EyeOff, Smartphone } from "lucide-react";
import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { LoginFlow } from "@/components/auth/login-flow";
import { TenantName } from "@/components/auth/tenant-name";
import { BrandArcs } from "@/components/brand/brand-arcs";
import { Logo } from "@/components/brand/logo";
import { LanguageSwitcher } from "@/components/language-switcher";
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
      <aside className="relative isolate m-3 hidden overflow-hidden rounded-3xl bg-panel text-panel-foreground lg:flex lg:flex-col lg:justify-between lg:p-12">
        <BrandArcs className="absolute inset-y-0 end-0 -z-10 h-full w-4/5 opacity-80" />
        <div
          aria-hidden="true"
          className="absolute inset-0 -z-10 bg-linear-to-r from-panel via-panel/85 to-transparent rtl:bg-linear-to-l"
        />
        <Link href="/" className="relative w-fit rounded-lg">
          <Logo />
        </Link>
        <div className="relative grid max-w-md gap-6">
          <p className="font-display text-4xl leading-[1.05] font-semibold tracking-tight xl:text-5xl">
            {t("brandHeading")}
          </p>
          <p className="text-lg text-panel-muted-foreground">
            {t("brandBody")}
          </p>
          <ul className="grid gap-2.5">
            {points.map(({ icon: Icon, text }) => (
              <li
                key={text}
                className="flex w-fit items-center gap-3 rounded-full border border-panel-border bg-panel/70 py-1.5 ps-1.5 pe-4 text-sm backdrop-blur"
              >
                <span className="grid size-7 place-items-center rounded-full bg-panel-foreground/10">
                  <Icon aria-hidden="true" className="size-3.5" />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>
        <p className="eyebrow relative text-panel-muted-foreground">
          {t("privacy")}
        </p>
      </aside>

      <div className="flex flex-col">
        <header className="flex items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <Link href="/" className="rounded-lg lg:invisible">
            <Logo />
          </Link>
          <LanguageSwitcher />
        </header>
        <main
          id="main"
          className="flex flex-1 items-start justify-center px-4 pt-6 pb-16 sm:items-center sm:px-6"
        >
          <div className="grid w-full max-w-md gap-4 motion-safe:animate-rise">
            <TenantName />
            <Card className="p-6 shadow-raised sm:p-8">
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
