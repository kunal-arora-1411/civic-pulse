import { useTranslations } from "next-intl";
import { Suspense } from "react";
import { LogoMark } from "@/components/brand/logo";
import { LanguageSwitcher } from "@/components/language-switcher";
import { Link } from "@/i18n/navigation";
import { Container } from "./primitives";
import { HeaderActions } from "./session-parts";

export function LandingHeader() {
  const t = useTranslations("landing.nav");
  const links = [
    { href: "#how-it-works", label: t("howItWorks") },
    { href: "#live-map", label: t("liveMap") },
    { href: "#for-cities", label: t("forCities") },
    { href: "/track", label: t("track") },
    { href: "/blog", label: t("blog") },
  ];

  return (
    <header className="lp-header sticky top-0 z-40 border-b border-lp-hair bg-white/85 backdrop-blur-md">
      <Container className="flex h-16 items-center justify-between gap-4">
        <div className="flex items-center gap-10">
          <Link
            href="/"
            aria-label={t("home")}
            className="flex items-center gap-2.5 rounded-lg"
          >
            <LogoMark className="size-[26px]" />
            <span
              aria-hidden="true"
              className="hidden text-lg font-semibold tracking-[-0.03em] text-lp-ink sm:inline"
            >
              CivicPulse
            </span>
          </Link>
          <nav aria-label={t("label")} className="hidden lg:block">
            <ul className="flex items-center gap-7 text-sm whitespace-nowrap text-lp-ink-2">
              {links.map((link) => (
                <li key={link.href}>
                  <a
                    href={link.href}
                    className="rounded transition-colors hover:text-lp-ink"
                  >
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        </div>
        <div className="flex items-center gap-2 sm:gap-3">
          <LanguageSwitcher />
          <Suspense fallback={null}>
            <HeaderActions />
          </Suspense>
        </div>
      </Container>
    </header>
  );
}
