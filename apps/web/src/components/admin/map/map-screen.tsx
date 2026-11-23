"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ExternalLink, List, MapPinOff, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  IssueFiltersBar,
  useFilterCategories,
} from "@/components/admin/issues/issue-filters";
import { useIssueFilters } from "@/components/admin/issues/use-issue-filters";
import { PageHeader } from "@/components/admin/page-header";
import { CategoryIcon } from "@/components/issues/category-icon";
import { StatusBadge } from "@/components/issues/status-badge";
import { IssuesMap } from "@/components/map/lazy-maps";
import { Alert } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useErrorMessage } from "@/hooks/use-error-message";
import { useLocalized, useTenantMapView } from "@/hooks/use-reference-data";
import { Link } from "@/i18n/navigation";
import {
  getIssuesGeoJson,
  type IssueStatus,
  listWardBoundaries,
} from "@/lib/api";
import { serializeIssueFilters, toFilterParams } from "@/lib/issues/filters";
import {
  type Bbox,
  clearCluster,
  EMPTY_SELECTION,
  listScrollTarget,
  type MapSelection,
  mapFocusTarget,
  reconcileSelection,
  roundBbox,
  selectCluster,
  selectFromList,
  selectFromMap,
  visibleListItems,
} from "@/lib/issues/map-selection";
import { cn } from "@/lib/utils";

/**
 * The staff map (FR-045, FR-046, FR-050): issues in the visible area,
 * clustered, over ward outlines, with a list that stays in sync. The
 * filters are the work queue's, read from the same URL parameters, so a
 * view moves between the two without losing anything.
 */
export function MapScreen() {
  const t = useTranslations("admin.map");
  const tStatus = useTranslations("issueStatus");
  const errorMessage = useErrorMessage();
  const localized = useLocalized();
  const view = useTenantMapView();
  const { filters, setFilters } = useIssueFilters();
  const categories = useFilterCategories();

  const [bbox, setBbox] = useState<Bbox | null>(null);
  const settledBbox = useDebouncedValue(bbox, 400);
  const queryBbox = settledBbox ? roundBbox(settledBbox) : null;
  const filterParams = toFilterParams(filters);

  const geojson = useQuery({
    queryKey: ["issues", "geojson", filterParams, queryBbox],
    queryFn: ({ signal }) =>
      getIssuesGeoJson({ ...filterParams, bbox: queryBbox as Bbox }, signal),
    enabled: queryBbox !== null,
    placeholderData: keepPreviousData,
  });
  const boundaries = useQuery({
    queryKey: ["admin", "wards", "geometry"],
    queryFn: ({ signal }) => listWardBoundaries(signal),
    staleTime: 60 * 60_000,
    select: (page) => page.items,
  });

  const features = useMemo(() => geojson.data?.features ?? [], [geojson.data]);
  const items = useMemo(
    () => features.map((feature) => feature.properties),
    [features],
  );

  const [selection, setSelection] = useState<MapSelection>(EMPTY_SELECTION);
  useEffect(() => {
    if (!geojson.data) return;
    const ids = new Set(features.map((feature) => feature.properties.id));
    setSelection((current) => reconcileSelection(current, ids));
  }, [geojson.data, features]);

  const listRef = useRef<HTMLUListElement>(null);
  const scrollTarget = listScrollTarget(selection);
  useEffect(() => {
    if (!scrollTarget) return;
    listRef.current
      ?.querySelector(`[data-issue-id="${CSS.escape(scrollTarget)}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [scrollTarget]);

  const categoryByCode = useMemo(
    () => new Map((categories.data ?? []).map((c) => [c.code, c])),
    [categories.data],
  );
  const markerLabel = useCallback(
    (reference: string, status: IssueStatus) =>
      `${reference}, ${tStatus(status)}`,
    [tStatus],
  );

  const shown = visibleListItems(items, selection);
  const listQuery = serializeIssueFilters({ ...filters, page: 1 }).toString();

  return (
    <div className="grid gap-4 motion-safe:animate-rise">
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Link
            href={listQuery ? `/admin/issues?${listQuery}` : "/admin/issues"}
            className={buttonVariants({ variant: "outline" })}
          >
            <List aria-hidden="true" />
            {t("listView")}
          </Link>
        }
      />
      <IssueFiltersBar filters={filters} onChange={setFilters} />

      {geojson.data?.truncated ? (
        <Alert variant="warning" live="polite" title={t("truncatedTitle")}>
          {t("truncatedBody", { count: features.length })}
        </Alert>
      ) : null}
      {geojson.isError ? (
        <Alert variant="destructive" live="assertive" title={t("loadError")}>
          <p>{errorMessage(geojson.error)}</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={() => geojson.refetch()}
          >
            {t("retry")}
          </Button>
        </Alert>
      ) : null}

      <div className="grid gap-4 lg:h-[calc(100dvh-24rem)] lg:min-h-[28rem] lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="relative h-[55dvh] min-h-80 overflow-hidden rounded-xl border border-border lg:h-full">
          <IssuesMap
            features={features}
            wards={boundaries.data ?? []}
            selectedId={selection.selectedId}
            focusId={mapFocusTarget(selection)}
            onSelect={(id) => setSelection((s) => selectFromMap(s, id))}
            onClusterSelect={(ids) => setSelection(selectCluster(ids))}
            onBoundsChange={setBbox}
            initialView={view}
            label={t("mapLabel")}
            markerLabel={markerLabel}
          />
          {geojson.isFetching ? (
            <output className="absolute end-3 top-3 z-[1000] rounded-full bg-card/95 px-3 py-1 text-xs font-semibold shadow-card">
              {t("updating")}
            </output>
          ) : null}
        </div>

        <section
          aria-labelledby="map-list-heading"
          className="flex min-h-0 flex-col rounded-xl border border-border bg-card shadow-card"
        >
          <div className="grid gap-2 border-b border-border p-4">
            <h2 id="map-list-heading" className="font-semibold">
              {selection.clusterIds ? t("clusterHeading") : t("listHeading")}
            </h2>
            <p aria-live="polite" className="text-sm text-muted-foreground">
              {geojson.data ? t("count", { count: shown.length }) : ""}
            </p>
            {selection.clusterIds ? (
              <Button
                variant="outline"
                size="sm"
                className="justify-self-start"
                onClick={() => setSelection((s) => clearCluster(s))}
              >
                <X aria-hidden="true" />
                {t("showAll")}
              </Button>
            ) : null}
          </div>
          {geojson.isPending ? (
            <div className="grid gap-2 p-4">
              <Skeleton className="h-14" />
              <Skeleton className="h-14" />
              <Skeleton className="h-14" />
            </div>
          ) : shown.length === 0 ? (
            <div className="grid flex-1 place-items-center p-6 text-center text-muted-foreground">
              <div className="grid justify-items-center gap-2">
                <MapPinOff aria-hidden="true" className="size-7" />
                <p>{t("empty")}</p>
              </div>
            </div>
          ) : (
            <ul
              ref={listRef}
              className="max-h-[50dvh] flex-1 divide-y divide-border overflow-y-auto lg:max-h-none"
            >
              {shown.map((item) => {
                const selected = item.id === selection.selectedId;
                const category = categoryByCode.get(item.category_code);
                return (
                  <li
                    key={item.id}
                    data-issue-id={item.id}
                    className={cn(
                      "relative flex items-stretch",
                      selected && "bg-primary-soft",
                    )}
                  >
                    {selected ? (
                      <span
                        aria-hidden="true"
                        className="absolute inset-y-0 start-0 w-1 bg-accent"
                      />
                    ) : null}
                    <button
                      type="button"
                      aria-pressed={selected}
                      onClick={() =>
                        setSelection((s) => selectFromList(s, item.id))
                      }
                      className="grid flex-1 gap-1 px-4 py-3 text-start hover:bg-muted/60"
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="font-mono text-sm font-semibold">
                          {item.reference}
                        </span>
                        <StatusBadge status={item.status} />
                      </span>
                      <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
                        <CategoryIcon
                          icon={category?.icon}
                          className="size-4"
                        />
                        {category
                          ? localized(category.name_i18n)
                          : item.category_code}
                        <span aria-hidden="true">·</span>
                        {t("reports", { count: item.report_count })}
                      </span>
                    </button>
                    <Link
                      href={`/admin/issues/${item.id}`}
                      className="grid w-11 shrink-0 place-items-center text-muted-foreground hover:bg-muted hover:text-foreground"
                      aria-label={t("open", { reference: item.reference })}
                    >
                      <ExternalLink aria-hidden="true" className="size-4" />
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
