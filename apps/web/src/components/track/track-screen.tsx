"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ChartColumn, HandHeart, MapPin, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useMemo, useState } from "react";
import { CategoryIcon } from "@/components/issues/category-icon";
import { StatusBadge } from "@/components/issues/status-badge";
import { IssuesMap, MapSkeleton } from "@/components/map/lazy-maps";
import { RemoteImage } from "@/components/media/remote-image";
import { Alert } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useErrorMessage } from "@/hooks/use-error-message";
import {
  useCategories,
  useLocalized,
  useTenantMapView,
} from "@/hooks/use-reference-data";
import { Link, useRouter } from "@/i18n/navigation";
import {
  getPublicIssuesGeojson,
  getScorecard,
  type IssueFeature,
  listPublicIssues,
  PUBLIC_SORTS,
  type PublicIssueItem,
  type PublicSort,
} from "@/lib/api";
import {
  DEFAULT_TRACK_FILTERS,
  isFiltered,
  PUBLIC_STATUSES,
  type StatusChoice,
  type TrackFilters,
  toQuery,
} from "@/lib/track/filters";

const PAGE_SIZE = 20;

/** Shared with the scorecard page: the ward list for the filter. */
export function usePublicScorecard() {
  return useQuery({
    queryKey: ["public", "scorecard"],
    queryFn: ({ signal }) => getScorecard(signal),
    staleTime: 60_000,
  });
}

function noop() {}

export function TrackSkeleton() {
  return (
    <div className="grid gap-4">
      <Skeleton className="h-10 w-full" />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <Skeleton className="h-[50dvh] rounded-xl" />
        <div className="grid content-start gap-3">
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-24 rounded-xl" />
        </div>
      </div>
    </div>
  );
}

function IssueRow({ issue }: { issue: PublicIssueItem }) {
  const t = useTranslations("track");
  const localized = useLocalized();
  const name = localized(issue.category.name_i18n);
  return (
    <Card className="transition-shadow hover:shadow-raised">
      <Link
        href={`/track/${issue.id}`}
        className="flex gap-3 rounded-xl p-3"
        data-issue-id={issue.id}
      >
        <RemoteImage
          src={issue.thumb_url}
          alt=""
          className="size-16 shrink-0 rounded-lg object-cover"
        />
        <div className="grid min-w-0 flex-1 gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={issue.status} />
            <span className="font-mono text-xs text-muted-foreground">
              {issue.reference}
            </span>
          </div>
          <p className="flex items-center gap-1.5 font-semibold">
            <CategoryIcon
              icon={issue.category.icon}
              className="size-4 shrink-0 text-primary"
            />
            <span className="truncate">{name}</span>
          </p>
          <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
            {issue.ward ? (
              <span className="inline-flex items-center gap-1">
                <MapPin aria-hidden="true" className="size-3.5" />
                {issue.ward.name}
              </span>
            ) : null}
            <span className="inline-flex items-center gap-1">
              <Users aria-hidden="true" className="size-3.5" />
              {t("reports", { count: issue.report_count })}
            </span>
            <span className="inline-flex items-center gap-1">
              <HandHeart aria-hidden="true" className="size-3.5" />
              {t("supporters", { count: issue.support_count })}
            </span>
            <span>{t("age", { count: Math.floor(issue.age_days) })}</span>
          </p>
        </div>
      </Link>
    </Card>
  );
}

/**
 * The public tracker: a clustered map coloured by status and a filterable,
 * sortable list. No sign-in. Filters live in component state rather than
 * the URL so the page stays in the static shell.
 */
export function TrackScreen() {
  const t = useTranslations("track");
  const tFilters = useTranslations("track.filters");
  const tStatus = useTranslations("issueStatus");
  const errorMessage = useErrorMessage();
  const localized = useLocalized();
  const router = useRouter();
  const view = useTenantMapView();
  const categories = useCategories();
  const scorecard = usePublicScorecard();
  const [filters, setFilters] = useState<TrackFilters>(DEFAULT_TRACK_FILTERS);
  const query = useMemo(() => toQuery(filters), [filters]);

  const geo = useQuery({
    queryKey: ["public", "geojson", query],
    queryFn: ({ signal }) => getPublicIssuesGeojson(query, signal),
  });
  const list = useInfiniteQuery({
    queryKey: ["public", "issues", query, filters.sort],
    queryFn: ({ signal, pageParam }) =>
      listPublicIssues(
        { ...query, sort: filters.sort, limit: PAGE_SIZE, offset: pageParam },
        signal,
      ),
    initialPageParam: 0,
    getNextPageParam: (last) => {
      const next = last.offset + last.items.length;
      return next < last.total ? next : undefined;
    },
  });

  const markerLabel = useCallback(
    ({ reference, status }: IssueFeature["properties"]) =>
      t("markerLabel", { reference, status: tStatus(status) }),
    [t, tStatus],
  );
  const features = geo.data?.features ?? [];
  const items = list.data?.pages.flatMap((page) => page.items) ?? [];
  const total = list.data?.pages[0]?.total ?? 0;
  const set = <K extends keyof TrackFilters>(key: K, value: TrackFilters[K]) =>
    setFilters((current) => ({ ...current, [key]: value }));

  return (
    <div className="grid gap-4 motion-safe:animate-rise">
      <fieldset className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[repeat(4,minmax(0,1fr))_auto] lg:items-end">
        <legend className="sr-only">{tFilters("label")}</legend>
        <div className="grid gap-1.5">
          <Label htmlFor="track-status">{tFilters("status")}</Label>
          <Select
            id="track-status"
            value={filters.status}
            onChange={(event) =>
              set("status", event.target.value as StatusChoice)
            }
          >
            <option value="">{tFilters("all")}</option>
            <option value="open">{tFilters("open")}</option>
            {PUBLIC_STATUSES.map((status) => (
              <option key={status} value={status}>
                {tStatus(status)}
              </option>
            ))}
          </Select>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="track-category">{tFilters("category")}</Label>
          <Select
            id="track-category"
            value={filters.category_id}
            onChange={(event) => set("category_id", event.target.value)}
          >
            <option value="">{tFilters("all")}</option>
            {(categories.data ?? []).map((category) => (
              <option key={category.id} value={category.id}>
                {localized(category.name_i18n)}
              </option>
            ))}
          </Select>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="track-ward">{tFilters("ward")}</Label>
          <Select
            id="track-ward"
            value={filters.ward_id}
            onChange={(event) => set("ward_id", event.target.value)}
          >
            <option value="">{tFilters("all")}</option>
            {(scorecard.data?.wards ?? []).map(({ ward }) => (
              <option key={ward.id} value={ward.id}>
                {ward.name}
              </option>
            ))}
          </Select>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="track-sort">{tFilters("sort")}</Label>
          <Select
            id="track-sort"
            value={filters.sort}
            onChange={(event) => set("sort", event.target.value as PublicSort)}
          >
            {PUBLIC_SORTS.map((sort) => (
              <option key={sort} value={sort}>
                {t(`sorts.${sort}`)}
              </option>
            ))}
          </Select>
        </div>
        <Button
          variant="ghost"
          disabled={!isFiltered(filters)}
          onClick={() =>
            setFilters({ ...DEFAULT_TRACK_FILTERS, sort: filters.sort })
          }
        >
          {tFilters("reset")}
        </Button>
      </fieldset>

      <div className="grid gap-4 lg:h-[calc(100dvh-20rem)] lg:min-h-[30rem] lg:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="grid gap-2 lg:h-full lg:grid-rows-[minmax(0,1fr)_auto]">
          <div className="relative h-[50dvh] min-h-72 overflow-hidden rounded-xl border border-border lg:h-full">
            {view.ready ? (
              <IssuesMap
                features={features}
                wards={[]}
                selectedId={null}
                focusId={null}
                onSelect={(id) => router.push(`/track/${id}`)}
                onClusterSelect={noop}
                onBoundsChange={noop}
                initialView={view}
                label={t("mapLabel")}
                markerLabel={markerLabel}
              />
            ) : (
              <MapSkeleton />
            )}
          </div>
          {geo.data?.truncated ? (
            <p className="text-sm text-muted-foreground">{t("truncated")}</p>
          ) : null}
        </div>

        <section
          aria-labelledby="track-results"
          className="grid content-start gap-3 lg:overflow-y-auto lg:pe-1"
        >
          <h2 id="track-results" className="font-semibold" aria-live="polite">
            {list.isSuccess ? t("results", { count: total }) : t("loading")}
          </h2>
          {list.isPending ? (
            <>
              <Skeleton className="h-24 rounded-xl" />
              <Skeleton className="h-24 rounded-xl" />
            </>
          ) : list.isError ? (
            <Alert
              variant="destructive"
              live="assertive"
              title={t("loadError")}
            >
              <p>{errorMessage(list.error)}</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() => list.refetch()}
              >
                {t("retry")}
              </Button>
            </Alert>
          ) : items.length === 0 ? (
            <p className="text-muted-foreground">{t("empty")}</p>
          ) : (
            <>
              <ul className="grid gap-3">
                {items.map((issue) => (
                  <li key={issue.id}>
                    <IssueRow issue={issue} />
                  </li>
                ))}
              </ul>
              {list.hasNextPage ? (
                <Button
                  variant="outline"
                  loading={list.isFetchingNextPage}
                  onClick={() => list.fetchNextPage()}
                >
                  {t("more")}
                </Button>
              ) : null}
            </>
          )}
        </section>
      </div>
    </div>
  );
}

export function ScorecardLink() {
  const t = useTranslations("track");
  return (
    <Link
      href="/track/scorecard"
      className={buttonVariants({ variant: "outline" })}
    >
      <ChartColumn aria-hidden="true" />
      {t("scorecardLink")}
    </Link>
  );
}
