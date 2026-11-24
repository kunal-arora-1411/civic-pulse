"use client";

import { useFormatter, useTranslations } from "next-intl";
import { type ReactNode, useState } from "react";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  LabelList,
  Line,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { duration } from "@/lib/analytics/format";
import {
  STATUS_GROUPS,
  type StatusGroupKey,
} from "@/lib/analytics/status-groups";
import type { Activity, ResolutionTimes } from "@/lib/api";
import { cn } from "@/lib/utils";

/*
 * The chart bodies. Each takes rows already shaped for drawing; the screen
 * owns fetching and the card owns states. Marks are thin, axes and grid
 * recessive, and colours come from the --viz-* tokens so light and dark
 * each use their own validated steps.
 */

const AXIS = {
  stroke: "var(--viz-axis)",
  tick: { fill: "var(--muted-foreground)", fontSize: 12 },
  tickLine: false,
} as const;

type TooltipRow = { name: string; value: string; color?: string };

function TooltipBox({
  title,
  rows,
}: {
  title?: ReactNode;
  rows: TooltipRow[];
}) {
  return (
    <div className="min-w-36 rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-card">
      {title ? <p className="mb-1 font-semibold">{title}</p> : null}
      <ul className="grid gap-0.5">
        {rows.map((row) => (
          <li key={row.name} className="flex items-center gap-2">
            {row.color ? (
              <span
                aria-hidden="true"
                className="size-2.5 shrink-0 rounded-sm"
                style={{ background: row.color }}
              />
            ) : null}
            <span className="text-muted-foreground">{row.name}</span>
            <span className="ms-auto font-medium tabular-nums">
              {row.value}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Legend with direct values: identity never rests on colour alone. */
export function SeriesLegend({
  items,
  className,
}: {
  items: { key: string; label: string; color: string; value?: string }[];
  className?: string;
}) {
  return (
    <ul className={cn("flex flex-wrap gap-x-4 gap-y-1 text-xs", className)}>
      {items.map((item) => (
        <li key={item.key} className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="size-2.5 rounded-sm"
            style={{ background: item.color }}
          />
          <span>{item.label}</span>
          {item.value ? (
            <span className="font-medium tabular-nums">{item.value}</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

// --- Trend -----------------------------------------------------------------

export type TrendRow = {
  label: string;
  reports: number;
  issues: number;
  resolved: number;
};

export const TREND_SERIES = [
  { key: "reports", color: "var(--viz-1)" },
  { key: "issues", color: "var(--viz-2)" },
  { key: "resolved", color: "var(--viz-3)" },
] as const;

export function TrendChart({ rows }: { rows: TrendRow[] }) {
  const t = useTranslations("admin.analytics.trend");
  const format = useFormatter();
  return (
    <div className="flex h-full flex-col gap-2">
      <SeriesLegend
        items={TREND_SERIES.map((s) => ({
          key: s.key,
          label: t(s.key),
          color: s.color,
        }))}
      />
      <div className="min-h-0 flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={rows}
            margin={{ top: 8, right: 8, left: -12, bottom: 0 }}
          >
            <CartesianGrid vertical={false} stroke="var(--viz-grid)" />
            <XAxis dataKey="label" {...AXIS} minTickGap={24} />
            <YAxis
              {...AXIS}
              axisLine={false}
              allowDecimals={false}
              width={44}
            />
            <Tooltip
              cursor={{ stroke: "var(--viz-axis)", strokeWidth: 1 }}
              content={({ active, label }) => {
                const row = rows.find((r) => r.label === label);
                if (!active || !row) return null;
                return (
                  <TooltipBox
                    title={label}
                    rows={TREND_SERIES.map((s) => ({
                      name: t(s.key),
                      value: format.number(row[s.key]),
                      color: s.color,
                    }))}
                  />
                );
              }}
            />
            <Area
              type="monotone"
              dataKey="reports"
              name={t("reports")}
              stroke="var(--viz-1)"
              strokeWidth={2}
              fill="var(--viz-1)"
              fillOpacity={0.12}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="issues"
              name={t("issues")}
              stroke="var(--viz-2)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="resolved"
              name={t("resolved")}
              stroke="var(--viz-3)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// --- Status: stacked bars by category, and the donut --------------------------

export type GroupedRow = { name: string } & Record<StatusGroupKey, number>;

export function useGroupLabels() {
  const t = useTranslations("admin.analytics.groups");
  return (key: StatusGroupKey) => t(key);
}

export function CategoryStatusChart({ rows }: { rows: GroupedRow[] }) {
  const groupLabel = useGroupLabels();
  const format = useFormatter();
  return (
    <div className="flex h-full flex-col gap-2">
      <SeriesLegend
        items={STATUS_GROUPS.map((g) => ({
          key: g.key,
          label: groupLabel(g.key),
          color: g.color,
        }))}
      />
      <div className="min-h-0 flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={rows}
            layout="vertical"
            margin={{ top: 4, right: 12, left: 0, bottom: 0 }}
            barCategoryGap="24%"
          >
            <CartesianGrid horizontal={false} stroke="var(--viz-grid)" />
            <XAxis type="number" {...AXIS} allowDecimals={false} />
            <YAxis
              type="category"
              dataKey="name"
              {...AXIS}
              axisLine={false}
              width={128}
            />
            <Tooltip
              cursor={{ fill: "var(--muted)" }}
              content={({ active, label }) => {
                const row = rows.find((r) => r.name === label);
                if (!active || !row) return null;
                return (
                  <TooltipBox
                    title={label}
                    rows={STATUS_GROUPS.map((g) => ({
                      name: groupLabel(g.key),
                      value: format.number(row[g.key]),
                      color: g.color,
                    }))}
                  />
                );
              }}
            />
            {STATUS_GROUPS.map((g, index) => (
              <Bar
                key={g.key}
                dataKey={g.key}
                name={groupLabel(g.key)}
                stackId="status"
                fill={g.color}
                stroke="var(--card)"
                strokeWidth={1}
                radius={index === STATUS_GROUPS.length - 1 ? [0, 4, 4, 0] : 0}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function StatusDonut({
  totals,
  total,
}: {
  totals: Record<StatusGroupKey, number>;
  total: number;
}) {
  const t = useTranslations("admin.analytics");
  const groupLabel = useGroupLabels();
  const format = useFormatter();
  const data = STATUS_GROUPS.map((g) => ({
    key: g.key,
    name: groupLabel(g.key),
    value: totals[g.key],
    color: g.color,
  }));
  const share = (n: number) =>
    format.number(total ? n / total : 0, {
      style: "percent",
      maximumFractionDigits: 0,
    });
  return (
    <div className="flex h-full flex-col items-center gap-4 sm:flex-row">
      <div className="relative h-44 w-44 shrink-0 sm:h-full sm:w-1/2">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Tooltip
              content={({ active, payload }) => {
                const item = payload?.[0]?.payload as
                  | (typeof data)[number]
                  | undefined;
                if (!active || !item) return null;
                return (
                  <TooltipBox
                    rows={[
                      {
                        name: item.name,
                        value: `${format.number(item.value)} · ${share(item.value)}`,
                        color: item.color,
                      },
                    ]}
                  />
                );
              }}
            />
            <Pie
              data={data.filter((d) => d.value > 0)}
              dataKey="value"
              nameKey="name"
              innerRadius="62%"
              outerRadius="92%"
              stroke="var(--card)"
              strokeWidth={2}
              isAnimationActive={false}
            >
              {data
                .filter((d) => d.value > 0)
                .map((d) => (
                  <Cell key={d.key} fill={d.color} />
                ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 grid place-content-center text-center">
          <span className="text-2xl font-semibold tabular-nums">
            {format.number(total)}
          </span>
          <span className="text-xs text-muted-foreground">
            {t("issuesTotal")}
          </span>
        </div>
      </div>
      <SeriesLegend
        className="grid gap-2 text-sm sm:flex-1"
        items={data.map((d) => ({
          key: d.key,
          label: d.name,
          color: d.color,
          value: `${format.number(d.value)} (${share(d.value)})`,
        }))}
      />
    </div>
  );
}

// --- Wards -------------------------------------------------------------------

export type WardBarRow = { name: string; issues: number; open: number };

export function WardRankingChart({ rows }: { rows: WardBarRow[] }) {
  const t = useTranslations("admin.analytics.wards");
  const format = useFormatter();
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart
        data={rows}
        layout="vertical"
        margin={{ top: 4, right: 36, left: 0, bottom: 0 }}
        barCategoryGap="28%"
      >
        <XAxis type="number" hide allowDecimals={false} />
        <YAxis
          type="category"
          dataKey="name"
          {...AXIS}
          axisLine={false}
          width={150}
        />
        <Tooltip
          cursor={{ fill: "var(--muted)" }}
          content={({ active, label }) => {
            const row = rows.find((r) => r.name === label);
            if (!active || !row) return null;
            return (
              <TooltipBox
                title={label}
                rows={[
                  {
                    name: t("issues"),
                    value: format.number(row.issues),
                    color: "var(--viz-1)",
                  },
                  { name: t("open"), value: format.number(row.open) },
                ]}
              />
            );
          }}
        />
        <Bar
          dataKey="issues"
          name={t("issues")}
          fill="var(--viz-1)"
          radius={[0, 4, 4, 0]}
          isAnimationActive={false}
        >
          <LabelList
            dataKey="issues"
            position="right"
            className="tabular-nums"
            fill="var(--foreground)"
            fontSize={12}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// --- Resolution time histogram -------------------------------------------------

export function useBinLabel() {
  const t = useTranslations("admin.analytics");
  const span = (h: number) => {
    const d = duration(h);
    return t(d.unit === "d" ? "days" : "hours", { value: d.value });
  };
  return (bin: ResolutionTimes["bins"][number]) =>
    bin.upper_hours === null
      ? t("binOpen", { from: span(bin.lower_hours) })
      : t("bin", {
          from: bin.lower_hours === 0 ? "0" : span(bin.lower_hours),
          to: span(bin.upper_hours),
        });
}

export function ResolutionHistogram({ data }: { data: ResolutionTimes }) {
  const t = useTranslations("admin.analytics");
  const format = useFormatter();
  const binLabel = useBinLabel();
  const rows = data.bins.map((bin) => ({
    label: binLabel(bin),
    count: bin.count,
  }));
  const median = data.median_hours;
  const medianBin =
    median === null
      ? undefined
      : data.bins.find(
          (b) =>
            median >= b.lower_hours &&
            (b.upper_hours === null || median < b.upper_hours),
        );
  const medianText =
    median === null
      ? null
      : (() => {
          const d = duration(median);
          return t(d.unit === "d" ? "days" : "hours", { value: d.value });
        })();
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart
        data={rows}
        margin={{ top: 24, right: 8, left: -12, bottom: 0 }}
        barCategoryGap={2}
      >
        <CartesianGrid vertical={false} stroke="var(--viz-grid)" />
        <XAxis dataKey="label" {...AXIS} interval={0} fontSize={11} />
        <YAxis {...AXIS} axisLine={false} allowDecimals={false} width={44} />
        <Tooltip
          cursor={{ fill: "var(--muted)" }}
          content={({ active, label }) => {
            const row = rows.find((r) => r.label === label);
            if (!active || !row) return null;
            return (
              <TooltipBox
                title={label}
                rows={[
                  {
                    name: t("resolution.issues"),
                    value: format.number(row.count),
                    color: "var(--viz-1)",
                  },
                ]}
              />
            );
          }}
        />
        <Bar
          dataKey="count"
          fill="var(--viz-1)"
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
        />
        {medianBin && medianText ? (
          <ReferenceLine
            x={binLabel(medianBin)}
            stroke="var(--foreground)"
            strokeDasharray="4 3"
            strokeWidth={1.5}
            label={{
              value: t("resolution.medianMarker", { value: medianText }),
              position: "top",
              fill: "var(--foreground)",
              fontSize: 12,
            }}
          />
        ) : null}
      </BarChart>
    </ResponsiveContainer>
  );
}

// --- Weekday x hour heatmap ------------------------------------------------------

// 1 January 2024 was a Monday; only the weekday name is used.
const MONDAY = Date.UTC(2024, 0, 1, 12);

export function useWeekdayNames(style: "short" | "long" = "short") {
  const format = useFormatter();
  return Array.from({ length: 7 }, (_, i) =>
    format.dateTime(new Date(MONDAY + i * 86_400_000), {
      weekday: style,
      timeZone: "UTC",
    }),
  );
}

export function ActivityHeatmap({ items }: { items: Activity["items"] }) {
  const t = useTranslations("admin.analytics.activity");
  const format = useFormatter();
  const days = useWeekdayNames();
  const longDays = useWeekdayNames("long");
  const [hover, setHover] = useState<{ d: number; h: number } | null>(null);
  const grid = Array.from({ length: 7 }, () => new Array<number>(24).fill(0));
  for (const cell of items) {
    const row = grid[cell.weekday];
    if (row && cell.hour >= 0 && cell.hour < 24) row[cell.hour] = cell.count;
  }
  const max = Math.max(1, ...items.map((i) => i.count));
  const hovered = hover ? (grid[hover.d]?.[hover.h] ?? 0) : null;
  const fill = (n: number) =>
    n === 0
      ? "var(--muted)"
      : `color-mix(in oklch, var(--viz-seq-hi) ${Math.round(15 + (85 * n) / max)}%, var(--viz-seq-lo))`;

  return (
    <div className="flex h-full flex-col gap-2">
      <p className="h-5 text-xs text-muted-foreground" aria-hidden="true">
        {hover && hovered !== null
          ? t("cell", {
              day: longDays[hover.d] ?? "",
              hour: String(hover.h).padStart(2, "0"),
              count: hovered,
            })
          : t("hint")}
      </p>
      <div className="overflow-x-auto" aria-hidden="true">
        <div
          className="grid min-w-[30rem] gap-0.5"
          style={{ gridTemplateColumns: "2.5rem repeat(24, minmax(0, 1fr))" }}
          onPointerOver={(event) => {
            const cell = (event.target as HTMLElement).dataset;
            if (cell.d !== undefined && cell.h !== undefined)
              setHover({ d: Number(cell.d), h: Number(cell.h) });
          }}
          onPointerLeave={() => setHover(null)}
        >
          {grid.map((row, d) => (
            <div key={days[d]} className="contents">
              <span className="pe-1 text-end text-xs leading-5 text-muted-foreground">
                {days[d]}
              </span>
              {row.map((n, h) => (
                <span
                  // biome-ignore lint/suspicious/noArrayIndexKey: the hour is the identity
                  key={h}
                  className={cn(
                    "h-5 rounded-[3px]",
                    hover?.d === d &&
                      hover.h === h &&
                      "outline-2 outline-foreground",
                  )}
                  style={{ background: fill(n) }}
                  data-d={d}
                  data-h={h}
                />
              ))}
            </div>
          ))}
          <span />
          {Array.from({ length: 24 }, (_, h) => (
            <span
              // biome-ignore lint/suspicious/noArrayIndexKey: the hour is the identity
              key={h}
              className="text-center text-[10px] text-muted-foreground"
            >
              {h % 3 === 0 ? String(h).padStart(2, "0") : ""}
            </span>
          ))}
        </div>
      </div>
      <div
        className="flex items-center gap-2 text-xs text-muted-foreground"
        aria-hidden="true"
      >
        <span>{t("fewer")}</span>
        <span
          className="h-2.5 w-24 rounded-sm"
          style={{
            background:
              "linear-gradient(90deg, color-mix(in oklch, var(--viz-seq-hi) 15%, var(--viz-seq-lo)), var(--viz-seq-hi))",
          }}
        />
        <span>{t("more", { max: format.number(max) })}</span>
      </div>
    </div>
  );
}

// --- AI quality gauges -------------------------------------------------------

function Gauge({
  label,
  value,
  note,
}: {
  label: string;
  value: number | null;
  note?: string;
}) {
  const t = useTranslations("admin.analytics");
  const format = useFormatter();
  const pct = value === null ? 0 : Math.max(0, Math.min(1, value)) * 100;
  const arc = "M 10 60 A 50 50 0 0 1 110 60";
  return (
    <li className="grid justify-items-center gap-1 text-center">
      <svg viewBox="0 0 120 68" className="w-full max-w-36" aria-hidden="true">
        <path
          d={arc}
          fill="none"
          stroke="var(--viz-grid)"
          strokeWidth={10}
          strokeLinecap="round"
        />
        {value !== null && pct > 0 ? (
          <path
            d={arc}
            fill="none"
            stroke="var(--viz-1)"
            strokeWidth={10}
            strokeLinecap="round"
            pathLength={100}
            strokeDasharray={`${pct} 100`}
          />
        ) : null}
        <text
          x="60"
          y="58"
          textAnchor="middle"
          className="fill-foreground text-[18px] font-semibold tabular-nums"
        >
          {value === null
            ? t("noValue")
            : format.number(value, {
                style: "percent",
                maximumFractionDigits: 0,
              })}
        </text>
      </svg>
      <span className="text-sm font-medium">{label}</span>
      {note ? (
        <span className="text-xs text-muted-foreground">{note}</span>
      ) : null}
    </li>
  );
}

export function QualityGauges({
  gauges,
}: {
  gauges: { key: string; label: string; value: number | null; note?: string }[];
}) {
  return (
    <ul className="grid h-full grid-cols-2 content-center gap-4 sm:grid-cols-4">
      {gauges.map((g) => (
        <Gauge key={g.key} label={g.label} value={g.value} note={g.note} />
      ))}
    </ul>
  );
}
