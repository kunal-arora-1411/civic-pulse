"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Inbox, MapPinPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { Alert } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { useErrorMessage } from "@/hooks/use-error-message";
import { Link } from "@/i18n/navigation";
import { listMyReports } from "@/lib/api";
import { ReportCard, ReportCardSkeleton } from "./report-card";

const PAGE_SIZE = 20;

export function useMyReports(pageSize = PAGE_SIZE) {
  return useInfiniteQuery({
    queryKey: ["reports", "mine", pageSize],
    queryFn: ({ pageParam, signal }) =>
      listMyReports({ limit: pageSize, offset: pageParam }, signal),
    initialPageParam: 0,
    getNextPageParam: (last) =>
      last.offset + last.items.length < last.total
        ? last.offset + last.items.length
        : undefined,
  });
}

export function NoReports() {
  const t = useTranslations("reports");
  return (
    <div className="relative grid justify-items-center gap-3 overflow-hidden rounded-3xl border border-border bg-card px-6 py-14 text-center shadow-card">
      <div
        aria-hidden="true"
        className="bg-survey-grid absolute inset-0 [mask-image:radial-gradient(ellipse_at_center,black,transparent_70%)]"
      />
      <span className="bg-brand-gradient relative grid size-14 place-items-center rounded-2xl text-white shadow-raised">
        <Inbox aria-hidden="true" className="size-6" />
      </span>
      <p className="relative text-xl font-semibold tracking-tight">
        {t("emptyTitle")}
      </p>
      <p className="relative max-w-sm text-muted-foreground">
        {t("emptyBody")}
      </p>
      <Link
        href="/report"
        className={buttonVariants({
          variant: "ink",
          className: "relative mt-2",
        })}
      >
        <MapPinPlus aria-hidden="true" />
        {t("emptyCta")}
      </Link>
    </div>
  );
}

export function MyReportsScreen() {
  const t = useTranslations("reports");
  const errorMessage = useErrorMessage();
  const query = useMyReports();
  const items = query.data?.pages.flatMap((page) => page.items) ?? [];
  const total = query.data?.pages[0]?.total ?? 0;

  if (query.isPending) {
    return (
      <div className="grid gap-3">
        <output className="sr-only">{t("loading")}</output>
        <ReportCardSkeleton />
        <ReportCardSkeleton />
        <ReportCardSkeleton />
      </div>
    );
  }
  if (query.isError) {
    return (
      <Alert variant="destructive" live="assertive" title={t("loadError")}>
        <p>{errorMessage(query.error)}</p>
        <Button
          variant="outline"
          size="sm"
          className="mt-3"
          onClick={() => query.refetch()}
        >
          {t("retry")}
        </Button>
      </Alert>
    );
  }
  if (items.length === 0) return <NoReports />;

  return (
    <div className="grid gap-4">
      <p className="eyebrow" aria-live="polite">
        {t("count", { count: total })}
      </p>
      <ul className="grid gap-3">
        {items.map((report) => (
          <li key={report.id}>
            <ReportCard report={report} />
          </li>
        ))}
      </ul>
      {query.hasNextPage ? (
        <Button
          variant="outline"
          className="justify-self-center"
          onClick={() => query.fetchNextPage()}
          loading={query.isFetchingNextPage}
        >
          {t("loadMore")}
        </Button>
      ) : null}
    </div>
  );
}
