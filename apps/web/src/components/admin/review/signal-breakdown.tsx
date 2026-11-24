"use client";

import {
  CircleCheck,
  CircleMinus,
  CircleX,
  Copy,
  type LucideIcon,
} from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import type { MatchSignals } from "@/lib/api";
import {
  matchVerdict,
  type SignalKey,
  signalRows,
  unit,
} from "@/lib/issues/signals";
import { cn } from "@/lib/utils";

/**
 * Why a report was matched to an issue (FR-037): each signal with its
 * evidence in plain units, its strength, its weight and what it added,
 * then the score against the review and auto-link thresholds.
 *
 * Everything is written out as text. The bars repeat the numbers for a
 * quick scan and are hidden from screen readers, and pass or fail is a
 * word with its own icon, never a colour alone.
 */
export function SignalBreakdown({
  signals,
  score,
  className,
}: {
  signals: MatchSignals;
  score: number;
  className?: string;
}) {
  const t = useTranslations("admin.review.signals");
  const format = useFormatter();
  const n2 = (value: number) =>
    format.number(value, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  const rows = signalRows(signals);
  const verdict = matchVerdict(score, signals);
  const { auto, review, visual_min } = signals.thresholds;

  const evidence: Record<
    SignalKey,
    { text: string; check?: { ok: boolean; label: string } }
  > = {
    geo: {
      text: t("distanceEvidence", {
        distance: format.number(signals.distance_m, {
          maximumFractionDigits: 0,
        }),
        radius: format.number(signals.radius_m, { maximumFractionDigits: 0 }),
      }),
      check: {
        ok: signals.distance_m <= signals.radius_m,
        label:
          signals.distance_m <= signals.radius_m
            ? t("withinRadius")
            : t("outsideRadius"),
      },
    },
    visual:
      signals.visual === null
        ? { text: t("visualUnavailableBody") }
        : {
            text: t("visualEvidence", { min: n2(visual_min) }),
            check: {
              ok: signals.visual >= visual_min,
              label:
                signals.visual >= visual_min
                  ? t("visualMeets")
                  : t("visualBelow"),
            },
          },
    category: {
      text: signals.category >= 1 ? t("categorySame") : t("categoryParent"),
    },
    time: {
      text: t("ageEvidence", {
        days: format.number(signals.age_days, { maximumFractionDigits: 1 }),
        count: signals.age_days,
      }),
    },
  };

  const verdictText =
    verdict.kind === "auto"
      ? t("outcomeAuto")
      : verdict.kind === "auto_blocked"
        ? t("outcomeAutoBlocked", { why: t(`blocked_${verdict.why}`) })
        : verdict.kind === "review"
          ? t("outcomeReview", { review: n2(review), auto: n2(auto) })
          : t("outcomeLow", { review: n2(review) });

  return (
    <div className={cn("grid gap-4", className)}>
      <section aria-label={t("scoreHeading")} className="grid gap-2">
        <p className="flex flex-wrap items-baseline justify-between gap-x-3">
          <span className="text-sm font-semibold">{t("score")}</span>
          <span className="font-mono text-lg font-semibold tabular-nums">
            {n2(score)}
          </span>
        </p>
        {/* The auto-link label sits above the bar and the review label
            below, so the two never collide on a narrow screen. */}
        <div aria-hidden="true" className="relative py-5">
          <div className="h-2.5 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary"
              style={{ width: `${unit(score) * 100}%` }}
            />
          </div>
          {[
            {
              value: auto,
              label: t("thresholdAuto", { value: n2(auto) }),
              above: true,
            },
            {
              value: review,
              label: t("thresholdReview", { value: n2(review) }),
              above: false,
            },
          ].map((tick) => (
            <span
              key={tick.label}
              className="absolute inset-y-0 w-0"
              style={{ left: `${unit(tick.value) * 100}%` }}
            >
              <span className="absolute inset-y-3.5 -left-px w-0.5 bg-foreground" />
              <span
                className={cn(
                  "absolute whitespace-nowrap text-[0.6875rem] leading-none font-semibold text-muted-foreground",
                  tick.above ? "top-0" : "bottom-0",
                  tick.value > 0.7
                    ? "right-0 -mr-px"
                    : tick.value < 0.3
                      ? "left-0"
                      : "left-0 -translate-x-1/2",
                )}
              >
                {tick.label}
              </span>
            </span>
          ))}
        </div>
        <p className="text-sm">{verdictText}</p>
      </section>

      <ul className="grid gap-3" aria-label={t("signalsHeading")}>
        {rows.map((row) => {
          const item = evidence[row.key];
          const CheckIcon: LucideIcon | null = item.check
            ? item.check.ok
              ? CircleCheck
              : CircleX
            : row.value === null
              ? CircleMinus
              : null;
          return (
            <li
              key={row.key}
              className="grid gap-1.5 rounded-lg border border-border p-3"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <p className="text-sm font-semibold">{t(`name_${row.key}`)}</p>
                <p className="font-mono text-sm tabular-nums">
                  {row.value === null ? (
                    t("visualUnavailable")
                  ) : (
                    <>
                      <span className="sr-only">{t("strength")} </span>
                      {n2(row.value)}
                    </>
                  )}
                </p>
              </div>
              <div
                aria-hidden="true"
                className="h-1.5 overflow-hidden rounded-full bg-muted"
              >
                {row.value === null ? null : (
                  <div
                    className="h-full rounded-full bg-foreground/70"
                    style={{ width: `${unit(row.value) * 100}%` }}
                  />
                )}
              </div>
              <p className="text-sm text-muted-foreground">{item.text}</p>
              <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs">
                {CheckIcon ? (
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 font-semibold",
                      item.check?.ok
                        ? "text-success-soft-foreground"
                        : item.check
                          ? "text-destructive-soft-foreground"
                          : "text-muted-foreground",
                    )}
                  >
                    <CheckIcon aria-hidden="true" className="size-3.5" />
                    {item.check?.label ?? t("visualUnavailable")}
                  </span>
                ) : (
                  <span />
                )}
                <span className="tabular-nums text-muted-foreground">
                  {t("contribution", {
                    weight: n2(row.weight),
                    points: n2(row.points),
                  })}
                </span>
              </div>
              {row.key === "visual" && signals.same_photo ? (
                <p className="inline-flex w-fit items-center gap-1.5 rounded-md bg-warning-soft px-2 py-1 text-xs font-semibold text-warning-soft-foreground">
                  <Copy aria-hidden="true" className="size-3.5" />
                  {t("samePhoto")}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
