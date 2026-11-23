"use client";

import { Check } from "lucide-react";
import { useTranslations } from "next-intl";
import { REPORT_STEPS, type ReportStep } from "@/lib/report/draft";
import { cn } from "@/lib/utils";

export const STEP_KEYS = {
  1: "photos",
  2: "location",
  3: "details",
  4: "review",
} as const satisfies Record<ReportStep, string>;

/**
 * Four labelled segments. Completed steps get a tick, the current one is
 * marked with aria-current="step", and "Step 2 of 4" is spelled out, so
 * progress isn't conveyed by colour alone.
 */
export function ReportProgress({
  step,
  furthest,
  onSelect,
}: {
  step: ReportStep;
  /** Steps up to here can be revisited by tapping them. */
  furthest: ReportStep;
  onSelect: (step: ReportStep) => void;
}) {
  const t = useTranslations("report");
  return (
    <nav aria-label={t("progressLabel")} className="grid gap-2">
      <p className="text-sm font-semibold text-muted-foreground">
        {t("stepOf", { current: step, total: REPORT_STEPS.length })}
      </p>
      <ol className="grid grid-cols-4 gap-1.5 sm:gap-2">
        {REPORT_STEPS.map((value) => {
          const current = value === step;
          const complete = value < step;
          const reachable = value <= furthest && !current;
          const label = t(`steps.${STEP_KEYS[value]}`);
          const content = (
            <>
              <span
                aria-hidden="true"
                className={cn(
                  "h-1.5 w-full rounded-full transition-colors",
                  current || complete ? "bg-primary" : "bg-border",
                )}
              />
              <span
                className={cn(
                  "flex items-center gap-1 text-xs font-semibold sm:text-sm",
                  current ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {complete ? (
                  <Check aria-hidden="true" className="size-3.5 shrink-0" />
                ) : null}
                <span className="truncate">{label}</span>
                {complete ? (
                  <span className="sr-only">{t("stepDone")}</span>
                ) : null}
              </span>
            </>
          );
          return (
            <li key={value} aria-current={current ? "step" : undefined}>
              {reachable ? (
                <button
                  type="button"
                  onClick={() => onSelect(value)}
                  className="grid w-full gap-1.5 rounded-md text-start hover:[&>span:last-child]:text-foreground"
                >
                  {content}
                </button>
              ) : (
                <div className="grid gap-1.5">{content}</div>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
