"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { PageHeader } from "@/components/admin/page-header";
import { HotspotMap } from "@/components/map/lazy-maps";
import { Button } from "@/components/ui/button";
import { useLocalized, useTenantMapView } from "@/hooks/use-reference-data";
import { isRangeInvalid, toQuery } from "@/lib/analytics/filters";
import { duration } from "@/lib/analytics/format";
import { groupStatuses, STATUS_GROUPS } from "@/lib/analytics/status-groups";
import {
  type AnalyticsQuery,
  getAnalyticsActivity,
  getAnalyticsByCategory,
  getAnalyticsByStatus,
  getAnalyticsByWard,
  getAnalyticsHotspots,
  getAnalyticsMatchingQuality,
  getAnalyticsOverview,
  getAnalyticsResolutionTimes,
  getAnalyticsTrend,
} from "@/lib/api";
import { AnalyticsFiltersBar } from "./analytics-filters";
import { ChartCard, DataTable } from "./chart-card";
import {
  ActivityHeatmap,
  CategoryStatusChart,
  QualityGauges,
  ResolutionHistogram,
  StatusDonut,
  TREND_SERIES,
  TrendChart,
  useBinLabel,
  useGroupLabels,
  useWeekdayNames,
  WardRankingChart,
} from "./charts";
import { ExportButton } from "./export-button";
import { KpiTiles } from "./kpi-tiles";
import { useAnalyticsFilters } from "./use-analytics-filters";

const WARD_LIMIT = 10;

function useAnalyticsQuery<T>(
  name: string,
  query: AnalyticsQuery,
  enabled: boolean,
  fetcher: (q: AnalyticsQuery, signal: AbortSignal) => Promise<T>,
) {
  return useQuery({
    queryKey: ["analytics", name, query],
    queryFn: ({ signal }) => fetcher(query, signal),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    enabled,
  });
}

/**
 * The analytics dashboard (AN-001 to AN-004): headline figures, then one
 * card per question. Every figure is defined in docs/metrics.md; the
 * filters live in the URL.
 */
export function AnalyticsScreen() {
  const t = useTranslations("admin.analytics");
  const tStatus = useTranslations("issueStatus");
  const format = useFormatter();
  const localized = useLocalized();
  const groupLabel = useGroupLabels();
  const binLabel = useBinLabel();
  const weekdays = useWeekdayNames("long");
  const view = useTenantMapView();
  const { filters, setFilters } = useAnalyticsFilters();
  const query = toQuery(filters);
  const enabled = !isRangeInvalid(filters);
  const n = (value: number) => format.number(value);
  const pct = (value: number | null) =>
    value === null
      ? t("noValue")
      : format.number(value, { style: "percent", maximumFractionDigits: 1 });
  const hours = (value: number | null) => {
    if (value === null) return t("noValue");
    const d = duration(value);
    return t(d.unit === "d" ? "days" : "hours", { value: d.value });
  };
  const day = (bucket: string) =>
    format.dateTime(new Date(`${bucket}T00:00:00+05:30`), {
      day: "numeric",
      month: "short",
    });

  const overview = useAnalyticsQuery(
    "overview",
    query,
    enabled,
    getAnalyticsOverview,
  );
  const trend = useQuery({
    queryKey: ["analytics", "trend", query, filters.interval],
    queryFn: ({ signal }) =>
      getAnalyticsTrend({ ...query, interval: filters.interval }, signal),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    enabled,
  });
  const byStatus = useAnalyticsQuery(
    "by-status",
    query,
    enabled,
    getAnalyticsByStatus,
  );
  const byCategory = useAnalyticsQuery(
    "by-category",
    query,
    enabled,
    getAnalyticsByCategory,
  );
  const byWard = useAnalyticsQuery(
    "by-ward",
    query,
    enabled,
    getAnalyticsByWard,
  );
  const resolution = useAnalyticsQuery(
    "resolution-times",
    query,
    enabled,
    getAnalyticsResolutionTimes,
  );
  const matching = useAnalyticsQuery(
    "matching-quality",
    query,
    enabled,
    getAnalyticsMatchingQuality,
  );
  const hotspots = useAnalyticsQuery(
    "hotspots",
    query,
    enabled,
    getAnalyticsHotspots,
  );
  const activity = useAnalyticsQuery(
    "activity",
    query,
    enabled,
    getAnalyticsActivity,
  );

  const trendRows = (trend.data?.points ?? []).map((p) => ({
    label:
      filters.interval === "week"
        ? t("trend.weekOf", { day: day(p.bucket) })
        : day(p.bucket),
    reports: p.reports,
    issues: p.issues,
    resolved: p.resolved,
  }));
  const trendTotals = trendRows.reduce(
    (acc, r) => ({
      reports: acc.reports + r.reports,
      issues: acc.issues + r.issues,
      resolved: acc.resolved + r.resolved,
    }),
    { reports: 0, issues: 0, resolved: 0 },
  );

  const statusTotals = groupStatuses(byStatus.data?.items ?? []);
  const categoryRows = (byCategory.data?.items ?? []).map((row) => ({
    name: localized(row.category.name_i18n),
    id: row.category.id,
    total: row.total,
    statuses: row.statuses,
    ...groupStatuses(row.statuses),
  }));
  const wardRows = (byWard.data?.items ?? []).map((row) => ({
    key: row.ward?.id ?? "none",
    name: row.ward?.name ?? t("wards.outside"),
    issues: row.issues,
    open: row.open,
    resolved: row.resolved,
    median: row.median_resolution_hours,
  }));
  const topWards = wardRows.slice(0, WARD_LIMIT);
  const hotspotItems = hotspots.data?.items ?? [];
  const activityItems = activity.data?.items ?? [];
  const busiest = activityItems.reduce<(typeof activityItems)[number] | null>(
    (best, c) => (best === null || c.count > best.count ? c : best),
    null,
  );
  const gauges = matching.data
    ? [
        {
          key: "auto_link_rate",
          label: t("quality.auto_link_rate"),
          value: matching.data.auto_link_rate,
        },
        {
          key: "review_rate",
          label: t("quality.review_rate"),
          value: matching.data.review_rate,
        },
        {
          key: "duplicate_rate",
          label: t("quality.duplicate_rate"),
          value: matching.data.duplicate_rate,
        },
        {
          key: "correction_rate",
          label: t("quality.correction_rate"),
          value: matching.data.correction_rate,
          note: t("quality.feedback", { count: matching.data.feedback_count }),
        },
      ]
    : [];

  return (
    <div className="motion-safe:animate-rise">
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={<ExportButton filters={filters} />}
      />
      <AnalyticsFiltersBar filters={filters} onChange={setFilters} />

      <div className="grid gap-4">
        <KpiTiles kpis={overview.data?.kpis} state={overview} />

        <div className="grid gap-4 lg:grid-cols-3">
          <ChartCard
            className="lg:col-span-2"
            title={t("trend.title")}
            description={t("trend.description")}
            state={trend}
            empty={trendRows.every(
              (r) => !r.reports && !r.issues && !r.resolved,
            )}
            summary={t("trend.summary", trendTotals)}
            actions={
              <fieldset className="flex rounded-lg border border-border p-0.5">
                <legend className="sr-only">{t("trend.interval")}</legend>
                {(["day", "week"] as const).map((interval) => (
                  <Button
                    key={interval}
                    size="sm"
                    variant={
                      filters.interval === interval ? "secondary" : "ghost"
                    }
                    aria-pressed={filters.interval === interval}
                    className="h-7"
                    onClick={() => setFilters({ interval })}
                  >
                    {t(`trend.${interval}`)}
                  </Button>
                ))}
              </fieldset>
            }
            table={() => (
              <DataTable
                label={t("trend.title")}
                columns={[
                  { key: "bucket", label: t("trend.period") },
                  ...TREND_SERIES.map((s) => ({
                    key: s.key,
                    label: t(`trend.${s.key}`),
                    numeric: true,
                  })),
                ]}
                rows={trendRows.map((r) => ({
                  key: r.label,
                  cells: [r.label, n(r.reports), n(r.issues), n(r.resolved)],
                }))}
              />
            )}
          >
            {() => <TrendChart rows={trendRows} />}
          </ChartCard>

          <ChartCard
            title={t("status.title")}
            description={t("status.description")}
            state={byStatus}
            empty={!byStatus.data?.total}
            summary={t("status.summary", {
              total: byStatus.data?.total ?? 0,
              done: statusTotals.done,
            })}
            table={() => (
              <DataTable
                label={t("status.title")}
                columns={[
                  { key: "status", label: t("status.status") },
                  { key: "count", label: t("status.count"), numeric: true },
                ]}
                rows={(byStatus.data?.items ?? []).map((item) => ({
                  key: item.status,
                  cells: [tStatus(item.status), n(item.count)],
                }))}
              />
            )}
          >
            {() => (
              <StatusDonut
                totals={statusTotals}
                total={byStatus.data?.total ?? 0}
              />
            )}
          </ChartCard>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <ChartCard
            title={t("category.title")}
            description={t("category.description")}
            state={byCategory}
            empty={categoryRows.length === 0}
            summary={
              categoryRows[0]
                ? t("category.summary", {
                    name: categoryRows[0].name,
                    count: categoryRows[0].total,
                  })
                : undefined
            }
            height="h-80"
            table={() => (
              <DataTable
                label={t("category.title")}
                columns={[
                  { key: "category", label: t("category.category") },
                  ...STATUS_GROUPS.map((g) => ({
                    key: g.key,
                    label: groupLabel(g.key),
                    numeric: true,
                  })),
                  { key: "total", label: t("category.total"), numeric: true },
                ]}
                rows={categoryRows.map((r) => ({
                  key: r.id,
                  cells: [
                    r.name,
                    ...STATUS_GROUPS.map((g) => n(r[g.key])),
                    n(r.total),
                  ],
                }))}
              />
            )}
          >
            {() => <CategoryStatusChart rows={categoryRows} />}
          </ChartCard>

          <ChartCard
            title={t("wards.title")}
            description={t("wards.description", { count: WARD_LIMIT })}
            state={byWard}
            empty={wardRows.length === 0}
            summary={
              topWards[0]
                ? t("wards.summary", {
                    name: topWards[0].name,
                    count: topWards[0].issues,
                  })
                : undefined
            }
            height="h-80"
            table={() => (
              <DataTable
                label={t("wards.title")}
                columns={[
                  { key: "ward", label: t("wards.ward") },
                  { key: "issues", label: t("wards.issues"), numeric: true },
                  { key: "open", label: t("wards.open"), numeric: true },
                  {
                    key: "resolved",
                    label: t("wards.resolved"),
                    numeric: true,
                  },
                  { key: "median", label: t("wards.median"), numeric: true },
                ]}
                rows={wardRows.map((r) => ({
                  key: r.key,
                  cells: [
                    r.name,
                    n(r.issues),
                    n(r.open),
                    n(r.resolved),
                    hours(r.median),
                  ],
                }))}
              />
            )}
          >
            {() => <WardRankingChart rows={topWards} />}
          </ChartCard>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <ChartCard
            title={t("resolution.title")}
            description={t("resolution.description")}
            state={resolution}
            empty={!resolution.data?.count}
            summary={t("resolution.summary", {
              count: resolution.data?.count ?? 0,
              median: hours(resolution.data?.median_hours ?? null),
              p90: hours(resolution.data?.p90_hours ?? null),
            })}
            table={() => (
              <DataTable
                label={t("resolution.title")}
                columns={[
                  { key: "bin", label: t("resolution.bin") },
                  {
                    key: "count",
                    label: t("resolution.issues"),
                    numeric: true,
                  },
                ]}
                rows={[
                  ...(resolution.data?.bins ?? []).map((bin) => ({
                    key: String(bin.lower_hours),
                    cells: [binLabel(bin), n(bin.count)],
                  })),
                  {
                    key: "median",
                    cells: [
                      t("resolution.median"),
                      hours(resolution.data?.median_hours ?? null),
                    ],
                  },
                  {
                    key: "mean",
                    cells: [
                      t("resolution.mean"),
                      hours(resolution.data?.mean_hours ?? null),
                    ],
                  },
                  {
                    key: "p90",
                    cells: [
                      t("resolution.p90"),
                      hours(resolution.data?.p90_hours ?? null),
                    ],
                  },
                ]}
              />
            )}
          >
            {() =>
              resolution.data ? (
                <ResolutionHistogram data={resolution.data} />
              ) : null
            }
          </ChartCard>

          <ChartCard
            title={t("activity.title")}
            description={t("activity.description")}
            state={activity}
            empty={activityItems.length === 0}
            summary={
              busiest
                ? t("activity.summary", {
                    day: weekdays[busiest.weekday] ?? "",
                    hour: String(busiest.hour).padStart(2, "0"),
                    count: busiest.count,
                  })
                : undefined
            }
            height="h-auto"
            table={() => (
              <DataTable
                label={t("activity.title")}
                columns={[
                  { key: "day", label: t("activity.day") },
                  { key: "hour", label: t("activity.hour") },
                  { key: "count", label: t("activity.reports"), numeric: true },
                ]}
                rows={[...activityItems]
                  .sort((a, b) => a.weekday - b.weekday || a.hour - b.hour)
                  .map((c) => ({
                    key: `${c.weekday}-${c.hour}`,
                    cells: [
                      weekdays[c.weekday] ?? "",
                      `${String(c.hour).padStart(2, "0")}:00`,
                      n(c.count),
                    ],
                  }))}
              />
            )}
          >
            {() => <ActivityHeatmap items={activityItems} />}
          </ChartCard>
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <ChartCard
            className="lg:col-span-2"
            title={t("hotspots.title")}
            description={t("hotspots.description")}
            state={hotspots}
            empty={hotspotItems.length === 0}
            summary={t("hotspots.summary", {
              cells: hotspotItems.length,
              max: hotspotItems[0]?.issues ?? 0,
            })}
            height="h-96"
            table={() => (
              <DataTable
                label={t("hotspots.title")}
                columns={[
                  { key: "where", label: t("hotspots.where") },
                  { key: "issues", label: t("hotspots.issues"), numeric: true },
                  { key: "open", label: t("hotspots.open"), numeric: true },
                ]}
                rows={hotspotItems.map((h) => ({
                  key: h.cell,
                  cells: [
                    `${h.lat.toFixed(4)}, ${h.lng.toFixed(4)}`,
                    n(h.issues),
                    n(h.open),
                  ],
                }))}
              />
            )}
          >
            {() => (
              <div className="flex h-full flex-col gap-2">
                <div className="min-h-0 flex-1">
                  {view.ready ? (
                    <HotspotMap
                      label={t("hotspots.title")}
                      center={view.center}
                      zoom={view.zoom}
                      cells={hotspotItems.map((h) => ({
                        cell: h.cell,
                        issues: h.issues,
                        open: h.open,
                        label: t("hotspots.tooltip", {
                          issues: h.issues,
                          open: h.open,
                        }),
                      }))}
                    />
                  ) : null}
                </div>
                <div
                  className="flex items-center gap-2 text-xs text-muted-foreground"
                  aria-hidden="true"
                >
                  <span>{t("activity.fewer")}</span>
                  <span className="h-2.5 w-24 rounded-sm bg-linear-to-r from-(--viz-1)/15 to-(--viz-1)/85" />
                  <span>
                    {t("activity.more", {
                      max: n(hotspotItems[0]?.issues ?? 0),
                    })}
                  </span>
                </div>
              </div>
            )}
          </ChartCard>

          <ChartCard
            title={t("quality.title")}
            description={t("quality.description", {
              count: matching.data?.decided_reports ?? 0,
            })}
            state={matching}
            empty={!matching.data?.decided_reports}
            summary={gauges
              .map((g) => `${g.label}: ${pct(g.value)}`)
              .join(", ")}
            height="h-auto"
            table={() => (
              <DataTable
                label={t("quality.title")}
                columns={[
                  { key: "metric", label: t("quality.metric") },
                  { key: "value", label: t("quality.value"), numeric: true },
                ]}
                rows={gauges.map((g) => ({
                  key: g.key,
                  cells: [g.label, pct(g.value)],
                }))}
              />
            )}
          >
            {() => <QualityGauges gauges={gauges} />}
          </ChartCard>
        </div>
      </div>
    </div>
  );
}
