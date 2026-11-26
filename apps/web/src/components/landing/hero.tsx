import { ArrowUp, Camera, ChevronRight, MapPin, Mic, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import type { CSSProperties } from "react";
import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";
import { CATEGORIES, PotholeIcon, STATS } from "./data";
import { CountUp, TypedText } from "./motion";
import { Container, photoGradient, Ribbon } from "./primitives";

const delay = (i: number) => ({ "--i": i }) as CSSProperties;

export function Hero() {
  const t = useTranslations("landing");

  return (
    <section aria-labelledby="lp-hero-title" className="relative overflow-clip">
      <Ribbon className="pointer-events-none absolute top-0 right-0 h-[980px] w-[1440px] max-w-none opacity-25 md:opacity-100" />

      <Container className="relative">
        {/* Vercel-style hairline guides on the content edges. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 inset-x-8 hidden border-x border-lp-hair lg:block"
        />

        <div className="relative grid justify-items-center pt-20 pb-20 text-center sm:pt-28 sm:pb-24">
          <h1
            id="lp-hero-title"
            className="max-w-[1000px] text-[42px] leading-[1.02] font-medium tracking-[-0.05em] text-lp-ink sm:text-[64px] lg:text-[84px] lg:leading-none lg:tracking-[-0.055em]"
          >
            <span className="lp-rise block" style={delay(0)}>
              {t("hero.titleLead")}
            </span>{" "}
            <span className="lp-rise block text-lp-mute" style={delay(2)}>
              {t("hero.titleMuted")}
            </span>
          </h1>

          <Link
            href="/report"
            style={delay(4)}
            className="lp-rise group mt-10 grid w-full max-w-[780px] gap-4 rounded-[22px] border border-lp-hair bg-white p-4 text-start shadow-[0_1px_2px_rgb(10_15_18/0.04),0_24px_60px_-12px_rgb(10_61_56/0.14)] transition-[border-color,box-shadow] duration-300 hover:border-[#d6dad5] hover:shadow-[0_1px_2px_rgb(10_15_18/0.05),0_30px_70px_-14px_rgb(10_61_56/0.22)] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-lp-teal-vivid sm:mt-12 sm:p-5"
          >
            {/* The name comes from this text, not aria-label: the visible
                content is a decorative preview, and an aria-label that
                doesn't contain the visible text fails WCAG 2.5.3. */}
            <span className="sr-only">{t("hero.composerLabel")}</span>
            <div aria-hidden="true" className="contents">
              <div className="flex items-center gap-2.5">
                <span
                  className={cn(
                    "size-12 shrink-0 rounded-[10px] sm:size-14",
                    photoGradient,
                  )}
                />
                <span className="inline-flex min-w-0 items-center gap-1.5 rounded-full bg-lp-wash py-1.5 ps-2.5 pe-3 text-[13px] font-medium text-lp-ink-2">
                  <MapPin
                    className="size-[15px] shrink-0 text-lp-teal"
                    strokeWidth={2}
                  />
                  <span className="truncate">{t("hero.location")}</span>
                </span>
              </div>
              <p className="min-h-[3.1em] text-[17px] leading-[1.45] tracking-[-0.015em] text-lp-ink sm:min-h-[1.5em] sm:text-[19px]">
                <TypedText examples={t.raw("hero.examples") as string[]} />
                <span className="lp-caret ms-0.5 inline-block h-[1.15em] w-0.5 translate-y-[0.2em] rounded-full bg-lp-teal-vivid" />
              </p>
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span className="grid size-[30px] place-items-center rounded-full border border-lp-hair text-lp-ink-2">
                    <Plus className="size-4" strokeWidth={2} />
                  </span>
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-lp-teal-soft py-1.5 ps-2.5 pe-3 text-[13px] font-medium text-lp-teal">
                    <PotholeIcon className="size-[15px]" strokeWidth={2} />
                    {t("hero.category")}
                  </span>
                  <span className="hidden items-center gap-1.5 rounded-full border border-lp-hair py-1.5 ps-2.5 pe-3 text-[13px] font-medium text-lp-ink-2 sm:inline-flex">
                    <Camera className="size-[15px]" strokeWidth={2} />
                    {t("hero.photos")}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-lp-ink-2">
                  <span className="hidden text-[13px] font-medium text-lp-mute-2 sm:inline">
                    {t("hero.languages")}
                  </span>
                  <Mic className="size-[18px]" strokeWidth={1.9} />
                  <span className="grid size-9 place-items-center rounded-full bg-lp-teal text-white transition-transform duration-300 group-hover:-translate-y-0.5">
                    <ArrowUp className="size-[18px]" strokeWidth={2.4} />
                  </span>
                </div>
              </div>
            </div>
          </Link>

          <nav
            aria-label={t("hero.railLabel")}
            className="lp-rise mt-4 w-full max-w-[780px]"
            style={delay(6)}
          >
            <ul className="grid grid-cols-3 gap-2.5 sm:grid-cols-6 sm:gap-3">
              {CATEGORIES.map(({ key, icon: Icon }, index) => (
                <li key={key}>
                  <Link
                    href="/report"
                    className={cn(
                      "group/tile relative flex h-[88px] flex-col justify-between rounded-[14px] p-3 text-start transition-[transform,border-color,box-shadow] duration-300 hover:-translate-y-0.5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lp-teal-vivid sm:h-[92px] sm:p-3.5",
                      index === 0
                        ? "bg-lp-ink text-white"
                        : "border border-lp-hair bg-white text-lp-ink hover:border-[#d6dad5] hover:shadow-[0_10px_24px_-14px_rgb(10_15_18/0.25)]",
                    )}
                  >
                    <Icon
                      aria-hidden="true"
                      className="size-[22px]"
                      strokeWidth={1.7}
                    />
                    <ChevronRight
                      aria-hidden="true"
                      className={cn(
                        "absolute end-3 top-3.5 size-3.5 transition-[opacity,transform] group-hover/tile:translate-x-0.5 group-hover/tile:opacity-60 rtl:rotate-180 sm:top-4",
                        index === 0 ? "opacity-100" : "opacity-0",
                      )}
                    />
                    <span className="text-sm leading-tight font-medium tracking-[-0.01em]">
                      {t(`categories.${key}`)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </nav>

          <p className="lp-rise mt-4 text-sm text-lp-mute-2" style={delay(7)}>
            {t("hero.helper")}
          </p>
        </div>
      </Container>

      <StatGrid />
    </section>
  );
}

function Crosshair({ className }: { className: string }) {
  return (
    <svg
      viewBox="0 0 13 13"
      aria-hidden="true"
      focusable="false"
      className={cn(
        "absolute hidden size-[13px] text-lp-mute lg:block",
        className,
      )}
    >
      <path d="M6.5 0v13M0 6.5h13" stroke="currentColor" />
    </svg>
  );
}

function StatGrid() {
  const t = useTranslations("landing.stats");
  const stats = [
    {
      label: t("resolved"),
      value: <CountUp value={STATS.resolved} />,
      note: t("resolvedNote"),
      live: true,
    },
    {
      label: t("median"),
      value: (
        <>
          <CountUp value={STATS.medianDays} decimals={1} /> {t("medianUnit")}
        </>
      ),
      note: t("medianNote"),
    },
    {
      label: t("wards"),
      value: <CountUp value={STATS.wards} />,
      note: t("wardsNote"),
    },
    {
      label: t("hindi"),
      value: <CountUp value={STATS.hindiShare} suffix="%" />,
      note: t("hindiNote"),
    },
  ];

  return (
    <Container className="relative">
      <Crosshair className="-top-[6.5px] left-[calc(2rem-6.5px)]" />
      <Crosshair className="-top-[6.5px] right-[calc(2rem-6.5px)]" />
      <dl
        aria-label={t("label")}
        className="relative grid grid-cols-2 border-t border-lp-hair bg-white lg:grid-cols-4 lg:border-x"
      >
        {stats.map((stat, index) => (
          <div
            key={stat.label}
            className={cn(
              "grid content-start gap-2.5 px-4 py-6 sm:px-7 sm:py-8",
              index % 2 === 0 && "border-e border-lp-hair",
              index < 2 && "border-b border-lp-hair lg:border-b-0",
              index === 1 && "lg:border-e",
            )}
          >
            <dt className="text-[13px] text-lp-mute-2">{stat.label}</dt>
            <dd className="text-[32px] leading-none font-medium tracking-[-0.04em] text-lp-ink sm:text-[44px]">
              {stat.value}
            </dd>
            <dd
              className={cn(
                "flex items-center gap-1.5 font-lp-mono text-xs",
                stat.live ? "text-lp-teal-text" : "text-lp-mute-2",
              )}
            >
              {stat.live ? (
                <span
                  aria-hidden="true"
                  className="lp-pulse size-1.5 rounded-full bg-lp-teal-vivid text-lp-teal-vivid/40"
                />
              ) : null}
              {stat.note}
            </dd>
          </div>
        ))}
      </dl>
      <p className="border-t border-lp-hair py-4 text-xs text-lp-mute-2 lg:border-x lg:px-7">
        {t("disclaimer")}
      </p>
    </Container>
  );
}
