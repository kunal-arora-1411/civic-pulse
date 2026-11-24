"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Inbox,
  Map as MapIcon,
} from "lucide-react";
import { useFormatter, useNow, useTranslations } from "next-intl";
import { useId } from "react";
import { PageHeader } from "@/components/admin/page-header";
import { Pagination } from "@/components/admin/pagination";
import { useOpenReviewCount } from "@/components/admin/review/use-open-review-count";
import { CategoryIcon } from "@/components/issues/category-icon";
import { PriorityBadge } from "@/components/issues/priority-badge";
import { StatusBadge } from "@/components/issues/status-badge";
import { RemoteImage } from "@/components/media/remote-image";
import { Alert } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useErrorMessage } from "@/hooks/use-error-message";
import { useLocalized } from "@/hooks/use-reference-data";
import { Link, useRouter } from "@/i18n/navigation";
import { ISSUE_SORTS, type IssueSort, listIssues } from "@/lib/api";
import {
  activeFilterCount,
  serializeIssueFilters,
  toListParams,
} from "@/lib/issues/filters";
import { IssueFiltersBar } from "./issue-filters";
import { useIssueFilters } from "./use-issue-filters";

const PAGE_SIZE = 25;
const COLUMNS = 8;

function SortHeader({
  label,
  sort,
  descending,
  ascending,
  onSort,
}: {
  label: string;
  sort: IssueSort;
  descending: IssueSort;
  ascending?: IssueSort;
  onSort: (sort: IssueSort) => void;
}) {
  const t = useTranslations("admin.issues");
  const active =
    sort === descending
      ? "descending"
      : sort === ascending
        ? "ascending"
        : null;
  const next: IssueSort =
    active === "descending" && ascending ? ascending : descending;
  const Icon =
    active === "descending"
      ? ArrowDown
      : active === "ascending"
        ? ArrowUp
        : ArrowUpDown;
  return (
    <TableHead aria-sort={active ?? "none"}>
      <button
        type="button"
        onClick={() => onSort(next)}
        className="-mx-1 inline-flex items-center gap-1 rounded px-1 uppercase hover:text-foreground"
      >
        {label}
        <Icon aria-hidden="true" className="size-3.5" />
        <span className="sr-only">
          {active ? t(`sortedBy.${active}`) : t("sortBy")}
        </span>
      </button>
    </TableHead>
  );
}

export function IssuesScreen() {
  const t = useTranslations("admin.issues");
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });
  const localized = useLocalized();
  const errorMessage = useErrorMessage();
  const router = useRouter();
  const { filters, setFilters } = useIssueFilters();
  // Reports waiting for a duplicate decision have no issue yet, so they
  // aren't in this list; say how many there are and where to find them.
  const openReviews = useOpenReviewCount();
  const sortId = useId();
  const params = toListParams(filters, PAGE_SIZE);

  const issues = useQuery({
    queryKey: ["issues", "list", params],
    queryFn: ({ signal }) => listIssues(params, signal),
    placeholderData: keepPreviousData,
  });

  const mapHref = (() => {
    const query = serializeIssueFilters({
      ...filters,
      sort: undefined,
      page: 1,
    }).toString();
    return query ? `/admin/map?${query}` : "/admin/map";
  })();
  const filtersActive = activeFilterCount(filters) > 0;

  return (
    <div className="motion-safe:animate-rise">
      <PageHeader
        section="issues"
        title={t("title")}
        description={t("description")}
        actions={
          <Link
            href={mapHref}
            className={buttonVariants({ variant: "outline" })}
          >
            <MapIcon aria-hidden="true" />
            {t("viewOnMap")}
          </Link>
        }
      />

      {openReviews > 0 ? (
        <Alert variant="info" className="mb-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p>{t("waitingForReview", { count: openReviews })}</p>
            <Link
              href="/admin/review"
              className={buttonVariants({ variant: "outline", size: "sm" })}
            >
              {t("openReview")}
            </Link>
          </div>
        </Alert>
      ) : null}

      <IssueFiltersBar
        filters={filters}
        onChange={setFilters}
        className="mb-4"
      />

      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <p aria-live="polite" className="text-sm text-muted-foreground">
          {issues.data ? t("resultCount", { count: issues.data.total }) : ""}
        </p>
        <div className="flex items-center gap-2 max-sm:w-full">
          <Label htmlFor={sortId} className="shrink-0">
            {t("sortLabel")}
          </Label>
          <Select
            id={sortId}
            value={filters.sort}
            onChange={(event) =>
              setFilters({ sort: event.target.value as IssueSort })
            }
            className="flex-1 sm:w-52 sm:flex-none"
          >
            {ISSUE_SORTS.map((sort) => (
              <option key={sort} value={sort}>
                {t(`sort.${sort}`)}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {issues.isError ? (
        <Alert
          variant="destructive"
          live="assertive"
          title={t("loadError")}
          className="mb-4"
        >
          <p>{errorMessage(issues.error)}</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={() => issues.refetch()}
          >
            {t("retry")}
          </Button>
        </Alert>
      ) : null}

      <Table
        label={t("tableLabel")}
        aria-busy={issues.isFetching || undefined}
        className="[&_td]:py-2"
      >
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-16 pe-0">
              <span className="sr-only">{t("colPhoto")}</span>
            </TableHead>
            <SortHeader
              label={t("colPriority")}
              sort={filters.sort}
              descending="-priority"
              onSort={(sort) => setFilters({ sort })}
            />
            <TableHead>{t("colReference")}</TableHead>
            <TableHead>{t("colCategory")}</TableHead>
            <TableHead>{t("colWard")}</TableHead>
            <SortHeader
              label={t("colReports")}
              sort={filters.sort}
              descending="-report_count"
              onSort={(sort) => setFilters({ sort })}
            />
            <TableHead>{t("colStatus")}</TableHead>
            <SortHeader
              label={t("colAge")}
              sort={filters.sort}
              descending="-created_at"
              ascending="created_at"
              onSort={(sort) => setFilters({ sort })}
            />
          </TableRow>
        </TableHeader>
        <TableBody>
          {issues.isPending ? (
            Array.from({ length: 8 }, (_, row) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: static placeholders
              <TableRow key={row}>
                <TableCell>
                  <Skeleton className="size-10 rounded-md" />
                </TableCell>
                {Array.from({ length: COLUMNS - 1 }, (_, cell) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: static placeholders
                  <TableCell key={cell}>
                    <Skeleton className="h-4 w-full max-w-28" />
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : issues.data?.items.length ? (
            issues.data.items.map((issue) => (
              <TableRow
                key={issue.id}
                className="cursor-pointer"
                onClick={(event) => {
                  // The reference link is the keyboard and screen reader
                  // path; the whole row is a larger mouse target.
                  if ((event.target as HTMLElement).closest("a")) return;
                  router.push(`/admin/issues/${issue.id}`);
                }}
              >
                <TableCell className="pe-0">
                  <RemoteImage
                    src={issue.thumb_url}
                    alt=""
                    width={40}
                    height={40}
                    className="size-10 max-w-none shrink-0 rounded-md"
                  />
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  {issue.priority ? (
                    <PriorityBadge
                      band={issue.priority.band}
                      score={issue.priority.score}
                      overridden={issue.priority.overridden}
                    />
                  ) : (
                    <span className="text-muted-foreground">
                      <span aria-hidden="true">—</span>
                      <span className="sr-only">{t("noPriority")}</span>
                    </span>
                  )}
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  <Link
                    href={`/admin/issues/${issue.id}`}
                    className="font-mono text-[0.8125rem] font-semibold text-primary underline-offset-4 hover:underline"
                  >
                    {issue.reference}
                  </Link>
                  {issue.address_text ? (
                    <span className="block max-w-56 truncate text-xs text-muted-foreground">
                      {issue.address_text}
                    </span>
                  ) : null}
                </TableCell>
                <TableCell>
                  <span className="flex items-center gap-1.5">
                    <CategoryIcon
                      icon={issue.category.icon}
                      className="size-4 shrink-0 text-muted-foreground"
                    />
                    <span className="max-w-44 truncate">
                      {localized(issue.category.name_i18n)}
                    </span>
                  </span>
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  {issue.ward?.name ?? "—"}
                </TableCell>
                <TableCell className="text-center tabular-nums">
                  {issue.report_count}
                </TableCell>
                <TableCell>
                  <StatusBadge status={issue.status} />
                </TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground">
                  <time
                    dateTime={issue.created_at}
                    title={format.dateTime(new Date(issue.created_at), {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })}
                  >
                    {format.relativeTime(new Date(issue.created_at), now)}
                  </time>
                </TableCell>
              </TableRow>
            ))
          ) : issues.isSuccess ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={COLUMNS}>
                <div className="grid justify-items-center gap-2 py-10 text-center">
                  <Inbox
                    aria-hidden="true"
                    className="size-8 text-muted-foreground"
                  />
                  <p className="font-semibold">
                    {filtersActive ? t("emptyFiltered") : t("empty")}
                  </p>
                </div>
              </TableCell>
            </TableRow>
          ) : null}
        </TableBody>
      </Table>

      {issues.data ? (
        <Pagination
          label={t("paginationLabel")}
          offset={issues.data.offset}
          limit={issues.data.limit}
          total={issues.data.total}
          onOffsetChange={(offset) =>
            setFilters({ page: Math.floor(offset / PAGE_SIZE) + 1 })
          }
        />
      ) : null}
    </div>
  );
}
