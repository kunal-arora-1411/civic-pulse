"use client";

import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useErrorMessage } from "@/hooks/use-error-message";
import { delta, deltaTone, duration } from "@/lib/analytics/format";
import type { Kpi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ChartState } from "./chart-card";

/** Tiles in this order; anything else the API adds is left out. */
export const KPI_ORDER = [
  "reports",
  "issues",
  "unique_reporters",
  "resolution_time",
  "acknowledgement_time",
  "duplicate_rate",
  "review_rate",
  "reopen_rate",
  "sla_compliance",
] as const;

export function useKpiFormat() {
  const format = useFormatter();
  const t = useTranslations("admin.analytics");
  return (unit: Kpi["unit"], value: number | null): string => {
    if (value === null) return t("noValue");
    if (unit === "ratio")
      return format.number(value, {
        style: "percent",
        maximumFractionDigits: 1,
      });
    if (unit === "hours") {
      const d = duration(value);
      return t(d.unit === "d" ? "days" : "hours", { value: d.value });
    }
    return format.number(value);
  };
}

/** A 2px line, no axes: the shape of the period, not its values. */
function Sparkline({ points }: { points: Kpi["sparkline"] }) {
  const values = points.map((p) => p.value);
  const present = values.filter((v): v is number => v !== null);
  if (present.length < 2) return <div className="h-8" />;
  const min = Math.min(...present);
  const max = Math.max(...present);
  const span = max - min || 1;
  const w = 120;
  const h = 32;
  const step = w / Math.max(values.length - 1, 1);
  // Gaps (no value that day) break the line rather than dropping to zero.
  const segments: string[] = [];
  let current = "";
  values.forEach((v, i) => {
    if (v === null) {
      if (current) segments.push(current);
      current = "";
      return;
    }
    const x = (i * step).toFixed(1);
    const y = (h - 2 - ((v - min) / span) * (h - 4)).toFixed(1);
    current += `${current ? "L" : "M"}${x},${y}`;
  });
  if (current) segments.push(current);
  return (
    <svg
      aria-hidden="true"
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      className="h-8 w-full overflow-visible"
    >
      <path
        d={segments.join("")}
        fill="none"
        stroke="var(--viz-1)"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

function KpiTile({
  kpi,
  metric,
}: {
  kpi: Kpi;
  metric: (typeof KPI_ORDER)[number];
}) {
  const t = useTranslations("admin.analytics");
  const format = useFormatter();
  const formatValue = useKpiFormat();
  const change = delta(kpi.unit, kpi.value, kpi.previous);
  const tone = change ? deltaTone(kpi.metric, change.change) : "neutral";
  const Arrow = !change
    ? ArrowRight
    : change.change > 0
      ? ArrowUpRight
      : change.change < 0
        ? ArrowDownRight
        : ArrowRight;
  const changeText = change
    ? change.kind === "points"
      ? t("deltaPoints", {
          value: format.number(change.change, {
            maximumFractionDigits: 1,
            signDisplay: "exceptZero",
          }),
        })
      : format.number(change.change, {
          style: "percent",
          maximumFractionDigits: 0,
          signDisplay: "exceptZero",
        })
    : null;

  return (
    <li className="grid gap-2 rounded-xl border border-border bg-card p-4 shadow-card">
      <h3 className="text-sm font-medium text-muted-foreground">
        {t(`kpi.${metric}`)}
      </h3>
      <p className="text-2xl font-semibold tabular-nums leading-none">
        {formatValue(kpi.unit, kpi.value)}
      </p>
      <Sparkline points={kpi.sparkline} />
      <p
        className={cn(
          "flex items-center gap-1 text-xs",
          tone === "good" && "text-(--viz-up)",
          tone === "bad" && "text-(--viz-down)",
          tone === "neutral" && "text-muted-foreground",
        )}
      >
        <Arrow aria-hidden="true" className="size-3.5 shrink-0" />
        {changeText ? (
          <span>
            {t(`tone.${tone}`, { change: changeText })}{" "}
            <span className="text-muted-foreground">
              {t("vsPrevious", {
                value: formatValue(kpi.unit, kpi.previous),
              })}
            </span>
          </span>
        ) : (
          <span>{t("noComparison")}</span>
        )}
      </p>
    </li>
  );
}

export function KpiTiles({
  kpis,
  state,
}: {
  kpis: Kpi[] | undefined;
  state: ChartState;
}) {
  const t = useTranslations("admin.analytics");
  const errorMessage = useErrorMessage();
  if (state.isError) {
    return (
      <Alert variant="destructive" title={t("error")} live="polite">
        <p>{errorMessage(state.error)}</p>
        <Button
          variant="outline"
          size="sm"
          className="mt-2"
          onClick={() => state.refetch()}
        >
          {t("retry")}
        </Button>
      </Alert>
    );
  }
  if (state.isPending || !kpis) {
    return (
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        {KPI_ORDER.map((key) => (
          <Skeleton key={key} className="h-36 rounded-xl" />
        ))}
        <output className="sr-only">{t("loading")}</output>
      </div>
    );
  }
  const byMetric = new Map(kpis.map((k) => [k.metric, k]));
  return (
    <ul
      aria-label={t("kpisLabel")}
      className="grid grid-cols-2 gap-3 lg:grid-cols-3"
    >
      {KPI_ORDER.map((metric) => {
        const kpi = byMetric.get(metric);
        return kpi ? <KpiTile key={metric} kpi={kpi} metric={metric} /> : null;
      })}
    </ul>
  );
}
