import { ChevronsLeftRight, MapPin, Maximize2 } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import {
  Container,
  muted,
  mutedSmall,
  photoGradient,
  StatusBadge,
} from "./primitives";

const shadow =
  "shadow-[0_1px_2px_rgb(10_15_18/0.05),0_16px_36px_-10px_rgb(10_15_18/0.14)]";

function Card({
  title,
  className,
  visualClassName,
  children,
}: {
  title: ReactNode;
  className?: string;
  visualClassName?: string;
  children: ReactNode;
}) {
  return (
    <article
      className={cn(
        "lp-reveal relative flex flex-col overflow-clip rounded-2xl border border-lp-hair bg-white",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-4 px-6 pt-6 sm:px-[26px] sm:pt-[26px]">
        <h3 className="max-w-[330px] text-[19px] leading-[1.3] font-medium tracking-[-0.02em] text-lp-ink sm:text-xl">
          {title}
        </h3>
        <span
          aria-hidden="true"
          className="grid size-7 shrink-0 place-items-center rounded-lg bg-lp-wash text-lp-ink-2"
        >
          <Maximize2 className="size-3.5" strokeWidth={2} />
        </span>
      </div>
      <div
        aria-hidden="true"
        className={cn("relative mt-6 shrink-0 grow", visualClassName)}
      >
        {children}
      </div>
    </article>
  );
}

export function Bento() {
  const t = useTranslations("landing.bento");

  return (
    <section
      id="how-it-works"
      aria-labelledby="lp-bento-title"
      className="scroll-mt-20 pb-24 sm:pb-34"
    >
      <Container className="grid gap-10 sm:gap-12">
        <h2
          id="lp-bento-title"
          className="lp-reveal max-w-[720px] text-[30px] leading-[1.12] font-medium tracking-[-0.035em] text-lp-ink sm:text-[40px] sm:leading-[1.1]"
        >
          {t.rich("title", { muted: muted() })}
        </h2>

        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-6">
          <Card
            title={t.rich("report.title", { muted: mutedSmall })}
            className="md:col-span-2 lg:col-span-4"
            visualClassName="h-[360px] sm:h-[400px]"
          >
            <ReportVisual />
          </Card>
          <Card
            title={t.rich("routed.title", { muted: mutedSmall })}
            className="lg:col-span-2"
            visualClassName="h-[340px] sm:h-[400px] bg-[linear-gradient(135deg,#0F5D57_0%,#16A08E_40%,#A6E8D8_72%,#F2B632_100%)]"
          >
            <RoutedVisual />
          </Card>
          <Card
            title={t.rich("updates.title", { muted: mutedSmall })}
            className="lg:col-span-2"
            visualClassName="h-[264px]"
          >
            <UpdatesVisual />
          </Card>
          <Card
            title={t.rich("proof.title", { muted: mutedSmall })}
            className="lg:col-span-2"
            visualClassName="h-[264px]"
          >
            <ProofVisual />
          </Card>
          <Card
            title={t.rich("hindi.title", { muted: mutedSmall })}
            className="md:col-span-2 lg:col-span-2"
            visualClassName="h-[264px]"
          >
            <HindiVisual />
          </Card>
        </div>
      </Container>
    </section>
  );
}

function ReportVisual() {
  const t = useTranslations("landing");
  return (
    <>
      <div className="absolute start-1/2 top-2 w-[230px] -translate-x-1/2 rounded-[36px] bg-lp-ink p-2 shadow-[0_30px_60px_-20px_rgb(10_15_18/0.45)] rtl:translate-x-1/2">
        <div className="overflow-clip rounded-[28px] bg-white">
          <svg
            aria-hidden="true"
            viewBox="0 0 214 170"
            className="block w-full"
          >
            <rect width="214" height="170" fill="#ECE7DA" />
            <path
              d="M0 62H214M0 134H214M70 0V170M160 0V170"
              stroke="#fff"
              strokeWidth="10"
            />
            <path d="M0 170 214 18" stroke="#FBF8EF" strokeWidth="14" />
            <circle cx="107" cy="94" r="26" fill="#16A08E" opacity="0.15" />
            <path
              d="M107 71c-8 0-14 6-14 13.5 0 10 12 19.6 13.3 20.6a1.2 1.2 0 0 0 1.4 0C109 104.1 121 94.5 121 84.5 121 77 115 71 107 71Z"
              fill="#F2B632"
              stroke="#fff"
              strokeWidth="2"
            />
          </svg>
          <div className="grid gap-3 p-3.5">
            <p className="text-sm font-medium text-lp-ink">
              {t("bento.report.what")}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {(["pothole", "streetlight", "garbage", "drain"] as const).map(
                (key, index) => (
                  <span
                    key={key}
                    className={cn(
                      "rounded-full px-2.5 py-1 text-[11px] font-medium",
                      index === 0
                        ? "bg-lp-ink text-white"
                        : "bg-lp-wash text-lp-ink-2",
                    )}
                  >
                    {t(`categories.${key}`)}
                  </span>
                ),
              )}
            </div>
            <div className="flex gap-1.5">
              <span className={cn("h-11 w-14 rounded-lg", photoGradient)} />
              <span className={cn("h-11 w-14 rounded-lg", photoGradient)} />
              <span className="h-11 w-14 rounded-lg border border-lp-hair bg-lp-wash" />
            </div>
            <span className="rounded-[10px] bg-lp-teal py-2.5 text-center text-[13px] font-medium text-white">
              {t("bento.report.send")}
            </span>
          </div>
        </div>
      </div>
      <div
        className={cn(
          "absolute end-6 top-16 hidden items-center gap-2.5 rounded-xl border border-lp-hair bg-white px-3 py-2.5 text-[13px] font-medium text-lp-ink sm:flex lg:end-[8%]",
          shadow,
        )}
      >
        {t("bento.report.uploading")}
        <span className="h-[5px] w-16 overflow-clip rounded-full bg-lp-wash">
          <span className="lp-fill block h-full w-full rounded-full bg-lp-teal-vivid" />
        </span>
        <span className="font-lp-mono text-[11px] font-normal text-lp-mute-2">
          82%
        </span>
      </div>
      <div
        className={cn(
          "absolute start-6 top-48 hidden items-center gap-2 rounded-xl border border-lp-hair bg-white px-3 py-2.5 text-[13px] font-medium text-lp-ink sm:flex lg:start-[9%]",
          shadow,
        )}
      >
        <MapPin className="size-[15px] text-lp-teal" strokeWidth={2} />
        {t("bento.report.located")}
      </div>
    </>
  );
}

function RoutedVisual() {
  const t = useTranslations("landing.bento.routed");
  const rows = [
    [t("report"), t("reportValue")],
    [t("ward"), t("wardValue")],
    [t("department"), t("departmentValue")],
    [t("assigned"), t("assignedValue")],
  ];
  return (
    <div className="absolute inset-x-6 top-12 mx-auto max-w-[280px] rounded-[14px] bg-white p-4 shadow-[0_24px_50px_-18px_rgb(10_15_18/0.45)] sm:top-14">
      <ol className="grid">
        {rows.map(([label, value], index) => (
          <li key={label} className="flex gap-3">
            <span className="flex flex-col items-center pt-1">
              <span
                className={cn(
                  "size-2.5 rounded-full",
                  index === rows.length - 1 ? "bg-lp-teal-vivid" : "bg-lp-ink",
                )}
              />
              {index < rows.length - 1 ? (
                <span className="h-9 w-[1.5px] bg-lp-hair" />
              ) : null}
            </span>
            <span className="grid gap-0.5 pb-1">
              <span className="font-lp-mono text-[10px] tracking-[0.06em] text-lp-mute-2 uppercase">
                {label}
              </span>
              <span className="text-sm font-medium text-lp-ink">{value}</span>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function UpdatesVisual() {
  const t = useTranslations("landing.bento.updates");
  const messages = [
    [t("first"), t("firstTime")],
    [t("second"), t("secondTime")],
    [t("third"), t("thirdTime")],
  ];
  return (
    <div className="grid gap-3 px-6 sm:px-[26px]">
      {messages.map(([text, time], index) => {
        const last = index === messages.length - 1;
        return (
          <div
            key={time}
            className={cn(
              "lp-reveal-late grid max-w-[260px] gap-1 rounded-[14px] px-3 py-2.5",
              last
                ? "justify-self-end bg-lp-teal text-white"
                : "bg-lp-wash text-lp-ink",
            )}
          >
            <span className="text-[13px] leading-[1.35]">{text}</span>
            <span
              className={cn(
                "font-lp-mono text-[10px]",
                last ? "text-white/70" : "text-lp-mute-2",
              )}
            >
              {time}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function ProofVisual() {
  const t = useTranslations("landing");
  return (
    <div className="px-6 sm:px-[26px]">
      <div className="relative h-[210px] overflow-clip rounded-xl" dir="ltr">
        <svg
          aria-hidden="true"
          viewBox="0 0 340 210"
          preserveAspectRatio="none"
          className="absolute inset-0 size-full"
        >
          <rect width="340" height="210" fill="#9E9788" />
          <ellipse cx="95" cy="128" rx="62" ry="22" fill="#4A4438" />
          <ellipse cx="95" cy="124" rx="46" ry="14" fill="#2F2B24" />
          <rect x="170" width="170" height="210" fill="#5E6266" />
          <path
            d="M170 105H340"
            stroke="#F4F1E8"
            strokeWidth="4"
            strokeDasharray="18 14"
          />
        </svg>
        <span className="lp-sweep absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 bg-white">
          <span className="absolute top-1/2 left-1/2 grid size-8 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-white text-lp-ink">
            <ChevronsLeftRight className="size-[18px]" strokeWidth={2.2} />
          </span>
        </span>
        <span className="absolute top-2.5 left-2.5 rounded-md bg-lp-ink px-2 py-0.5 font-lp-mono text-[10px] text-white">
          {t("bento.proof.before")}
        </span>
        <span className="absolute top-2.5 right-2.5 rounded-md bg-lp-teal px-2 py-0.5 font-lp-mono text-[10px] text-white">
          {t("bento.proof.after")}
        </span>
      </div>
      <div
        className={cn(
          "relative mx-auto -mt-5 flex w-fit items-center gap-2 rounded-[10px] border border-lp-hair bg-white py-2 ps-2.5 pe-3 text-[13px] font-medium text-lp-ink",
          shadow,
        )}
      >
        <StatusBadge tone="fixed">{t("status.fixed")}</StatusBadge>
        {t("bento.proof.confirmed")}
      </div>
    </div>
  );
}

function HindiVisual() {
  const t = useTranslations("landing.bento.hindi");
  return (
    <div className="grid content-start gap-4 px-6 sm:px-[26px]">
      <span className="flex w-fit gap-0.5 rounded-full bg-lp-wash p-1 text-[13px] font-medium">
        <span className="rounded-full px-3.5 py-1.5 text-lp-ink-2">
          {t("english")}
        </span>
        <span
          lang="hi"
          className="rounded-full bg-lp-ink px-3.5 py-1.5 text-white"
        >
          {t("hindi")}
        </span>
      </span>
      <div
        lang="hi"
        className={cn(
          "grid max-w-[300px] gap-2.5 rounded-[14px] border border-lp-hair bg-white p-4",
          shadow,
        )}
      >
        <span className="text-lg font-medium text-lp-ink">{t("sample")}</span>
        <span className="font-lp-mono text-[11px] text-lp-mute-2">
          {t("ward")}
        </span>
        <span className="w-fit">
          <StatusBadge tone="fixed">{t("status")}</StatusBadge>
        </span>
      </div>
    </div>
  );
}
