"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, MapPin } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { use } from "react";
import { CategoryIcon } from "@/components/issues/category-icon";
import { PublicTimeline } from "@/components/issues/public-timeline";
import { StatusBadge } from "@/components/issues/status-badge";
import { PinMap } from "@/components/map/lazy-maps";
import { PhotoGallery } from "@/components/media/photo-gallery";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useErrorMessage } from "@/hooks/use-error-message";
import { useCategories, useLocalized } from "@/hooks/use-reference-data";
import { Link } from "@/i18n/navigation";
import { type Category, getReport, isApiError, type Report } from "@/lib/api";
import { processingRefetchInterval } from "@/lib/media/processing";

/** "road_name" → "Road name", for fields of categories since edited. */
function humanize(key: string): string {
  const words = key.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function useDetailLabels(categoryId: string | undefined) {
  const { data } = useCategories();
  const localized = useLocalized();
  const t = useTranslations("report.details");
  const category: Category | undefined = data?.find((c) => c.id === categoryId);
  return (key: string, value: unknown) => {
    const field = category?.fields.find((f) => f.key === key);
    const label = field ? localized(field.label_i18n) : humanize(key);
    const option = field?.options?.find((o) => o.value === value);
    const text = option
      ? localized(option.label_i18n)
      : typeof value === "boolean"
        ? value
          ? t("yes")
          : t("no")
        : String(value);
    return { label, text };
  };
}

export function DetailSkeleton() {
  return (
    <div className="grid gap-4">
      <Skeleton className="h-8 w-2/3" />
      <Skeleton className="h-5 w-1/3" />
      <Skeleton className="h-48 rounded-xl" />
      <Skeleton className="h-32 rounded-xl" />
    </div>
  );
}

function Body({ report }: { report: Report }) {
  const t = useTranslations("reports.detail");
  const format = useFormatter();
  const localized = useLocalized();
  const detailLabel = useDetailLabels(report.category.id);
  const details = Object.entries(report.details ?? {}).filter(
    ([, value]) => value !== null && value !== "",
  );

  return (
    <div className="grid gap-6 motion-safe:animate-rise">
      <header className="grid gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {report.issue ? <StatusBadge status={report.issue.status} /> : null}
          <span className="font-mono text-sm text-muted-foreground">
            {report.reference}
          </span>
        </div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold sm:text-3xl">
          <CategoryIcon
            icon={report.category.icon}
            className="size-7 shrink-0 text-primary"
          />
          {localized(report.category.name_i18n)}
        </h1>
        <p className="text-sm text-muted-foreground">
          {t("reportedOn", {
            date: format.dateTime(new Date(report.created_at), {
              dateStyle: "long",
              timeStyle: "short",
            }),
          })}
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="grid content-start gap-6">
          <Card className="grid gap-3 p-5">
            <h2 className="font-semibold">{t("photos")}</h2>
            <PhotoGallery
              media={report.media}
              label={t("photosOf", { reference: report.reference })}
            />
          </Card>

          <Card className="grid gap-3 p-5">
            <h2 className="font-semibold">{t("location")}</h2>
            <div className="h-48 overflow-hidden rounded-lg border border-border">
              <PinMap
                center={report.location}
                zoom={16}
                pin={report.location}
                static
                label={t("mapLabel")}
                pinLabel={t("location")}
              />
            </div>
            <p className="flex items-start gap-2 text-sm">
              <MapPin aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              <span>
                {report.address_text || t("noAddress")}
                {report.ward ? (
                  <span className="block text-muted-foreground">
                    {report.ward.name}
                  </span>
                ) : null}
              </span>
            </p>
          </Card>

          <Card className="grid gap-3 p-5">
            <h2 className="font-semibold">{t("details")}</h2>
            {details.length > 0 ? (
              <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
                {details.map(([key, value]) => {
                  const { label, text } = detailLabel(key, value);
                  return (
                    <div key={key} className="contents">
                      <dt className="text-muted-foreground">{label}</dt>
                      <dd className="font-medium">{text}</dd>
                    </div>
                  );
                })}
              </dl>
            ) : null}
            <p className="whitespace-pre-line">
              {report.description || (
                <span className="text-muted-foreground">
                  {t("noDescription")}
                </span>
              )}
            </p>
          </Card>
        </div>

        <Card className="grid content-start gap-4 p-5">
          <div className="grid gap-1">
            <h2 className="font-semibold">{t("progress")}</h2>
            {report.issue ? (
              <p className="text-sm text-muted-foreground">
                {t("issueRef", { reference: report.issue.reference })}
              </p>
            ) : null}
          </div>
          {report.issue ? (
            <PublicTimeline events={report.issue.timeline} />
          ) : null}
        </Card>
      </div>
    </div>
  );
}

export function ReportDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useTranslations("reports.detail");
  const errorMessage = useErrorMessage();
  const query = useQuery({
    queryKey: ["reports", "detail", id],
    queryFn: ({ signal }) => getReport(id, signal),
    refetchInterval: ({ state }) =>
      processingRefetchInterval(state.data?.media, state.dataUpdateCount),
  });

  return (
    <div className="grid gap-5">
      <Link
        href="/reports"
        className="inline-flex w-fit items-center gap-1.5 rounded-md text-sm font-semibold text-primary hover:underline"
      >
        <ArrowLeft aria-hidden="true" className="size-4 rtl:rotate-180" />
        {t("back")}
      </Link>
      {query.isPending ? (
        <>
          <output className="sr-only">{t("loading")}</output>
          <DetailSkeleton />
        </>
      ) : query.isError ? (
        isApiError(query.error, "not_found") ? (
          <Alert variant="info" title={t("notFoundTitle")}>
            {t("notFoundBody")}
          </Alert>
        ) : (
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
        )
      ) : (
        <Body report={query.data} />
      )}
    </div>
  );
}
