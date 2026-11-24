import { useTranslations } from "next-intl";
import type { CSSProperties, ReactNode } from "react";
import { LogoMark } from "@/components/brand/logo";
import { Link } from "@/i18n/navigation";
import { CONTACT_URL } from "./data";
import { Container } from "./primitives";

const WORDMARK = "civicpulse";

function FooterLink({ href, children }: { href: string; children: ReactNode }) {
  const className =
    "rounded text-sm text-lp-mute-2 transition-colors hover:text-lp-ink";
  return href.startsWith("/") ? (
    <Link href={href} className={className}>
      {children}
    </Link>
  ) : (
    <a href={href} className={className}>
      {children}
    </a>
  );
}

export function LandingFooter() {
  const t = useTranslations("landing.footer");
  const columns: { title: string; links: [string, string][] }[] = [
    {
      title: t("product"),
      links: [
        ["/report", t("report")],
        ["/reports", t("myReports")],
        ["#how-it-works", t("howItWorks")],
        ["#live-map", t("liveMap")],
      ],
    },
    {
      title: t("cities"),
      links: [
        ["/admin", t("staffConsole")],
        ["/field", t("fieldApp")],
        ...(CONTACT_URL
          ? ([[CONTACT_URL, t("walkthrough")]] as [string, string][])
          : []),
      ],
    },
    {
      title: t("account"),
      links: [
        ["/login", t("signIn")],
        ["/profile", t("profile")],
      ],
    },
  ];

  return (
    <footer className="overflow-clip border-t border-lp-hair bg-white">
      <Container className="grid gap-12 pt-16 pb-8 sm:pt-18">
        <div className="flex flex-wrap justify-between gap-12">
          <div className="grid max-w-[300px] content-start gap-4">
            <span className="flex items-center gap-2.5">
              <LogoMark className="size-[26px]" />
              <span className="text-lg font-semibold tracking-[-0.03em] text-lp-ink">
                CivicPulse
              </span>
            </span>
            <p className="text-sm leading-[1.55] text-lp-mute-2">
              {t("blurb")}
            </p>
            <span className="flex w-fit items-center gap-2 rounded-full border border-lp-hair px-2.5 py-1 text-xs font-medium text-lp-ink-2">
              <span
                aria-hidden="true"
                className="lp-pulse size-[7px] rounded-full bg-lp-teal-vivid text-lp-teal-vivid/40"
              />
              {t("status")}
            </span>
          </div>
          <nav
            aria-label={t("label")}
            className="grid grid-cols-2 gap-x-12 gap-y-10 sm:grid-cols-3"
          >
            {columns.map((column) => (
              <div key={column.title} className="grid content-start gap-3">
                <h2 className="text-[13px] font-medium text-lp-ink">
                  {column.title}
                </h2>
                <ul className="grid gap-2.5">
                  {column.links.map(([href, label]) => (
                    <li key={href}>
                      <FooterLink href={href}>{label}</FooterLink>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </div>

        <p
          aria-hidden="true"
          className="-mb-[0.06em] text-center text-[clamp(52px,16.2vw,236px)] leading-[0.8] whitespace-nowrap font-semibold tracking-[-0.07em] select-none"
        >
          {Array.from(WORDMARK).map((letter, index) => (
            <span
              // biome-ignore lint/suspicious/noArrayIndexKey: letters repeat; position is the identity
              key={index}
              className="lp-letter bg-[linear-gradient(90deg,#0F5D57_0%,#16A08E_45%,#A6E8D8_75%,#F2B632_100%)] bg-clip-text text-transparent [background-size:1000%_100%]"
              style={
                {
                  "--i": index,
                  backgroundPosition: `${(index / (WORDMARK.length - 1)) * 100}% 0`,
                } as CSSProperties
              }
            >
              {letter}
            </span>
          ))}
        </p>

        <div className="flex flex-wrap items-center justify-between gap-4 text-xs text-lp-mute-2">
          <span className="font-lp-mono">{t("copyright")}</span>
          <span>{t("privacy")}</span>
        </div>
      </Container>
    </footer>
  );
}
