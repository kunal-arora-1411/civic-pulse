"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Combine, MapPin } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { use } from "react";
import { DetailSkeleton } from "@/components/citizen/report-detail";
import { SupportButton } from "@/components/community/support-button";
import { CategoryIcon } from "@/components/issues/category-icon";
import { PublicTimeline } from "@/components/issues/public-timeline";
import { StatusBadge } from "@/components/issues/status-badge";
import { PinMap } from "@/components/map/lazy-maps";
import { PhotoGallery } from "@/components/media/photo-gallery";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useErrorMessage } from "@/hooks/use-error-message";
import { useLocalized } from "@/hooks/use-reference-data";
import { Link } from "@/i18n/navigation";
import {
  getPublicIssue,
  isApiError,
  type Media,
  type PublicIssueDetail,
  type PublicPhoto,
} from "@/lib/api";

/** Public photos are blurred copies; the gallery wants the media shape. */
function asMedia(photos: PublicPhoto[]): Media[] {
  return photos.map((photo) => ({
    id: photo.display_url,
    status: "ready",
    thumb_url: photo.thumb_url,
    display_url: photo.display_url,
    original_url: null,
  }));
}

function Body({ issue }: { issue: PublicIssueDetail }) {
  const t = useTranslations("track.detail");
  const format = useFormatter();
  const localized = useLocalized();
  const point = { lat: issue.location.lat, lng: issue.location.lng };
  const supportable =
    !issue.merged_into && !["closed", "rejected"].includes(issue.status);

  return (
    <div className="grid gap-6 motion-safe:animate-rise">
      <header className="grid gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={issue.status} />
          <span className="font-mono text-sm text-muted-foreground">
            {issue.reference}
          </span>
        </div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold sm:text-3xl">
          <CategoryIcon
            icon={issue.category.icon}
            className="size-7 shrink-0 text-primary"
          />
          {localized(issue.category.name_i18n)}
        </h1>
        <p className="text-sm text-muted-foreground">
          {t("reportedOn", {
            date: format.dateTime(new Date(issue.created_at), {
              dateStyle: "long",
            }),
          })}
          {issue.ward ? ` · ${issue.ward.name}` : null}
        </p>
        <SupportButton
          issueId={issue.id}
          count={issue.support_count}
          open={supportable}
          returnTo={`/track/${issue.id}`}
        />
      </header>

      {issue.merged_into ? (
        <Alert variant="info">
          <span className="inline-flex items-center gap-2">
            <Combine aria-hidden="true" className="size-4" />
            {issue.merged_into_id
              ? t.rich("mergedInto", {
                  reference: issue.merged_into,
                  link: (chunks) => (
                    <Link
                      href={`/track/${issue.merged_into_id}`}
                      className="font-semibold underline underline-offset-2"
                    >
                      {chunks}
                    </Link>
                  ),
                })
              : t("mergedIntoPlain", { reference: issue.merged_into })}
          </span>
        </Alert>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="grid content-start gap-6">
          <Card className="grid gap-4 p-5">
            <div className="grid gap-2">
              <h2 className="font-semibold">{t("before")}</h2>
              {issue.before_photos.length > 0 ? (
                <PhotoGallery
                  media={asMedia(issue.before_photos)}
                  label={t("beforeOf", { reference: issue.reference })}
                />
              ) : (
                <p className="text-sm text-muted-foreground">{t("noPhotos")}</p>
              )}
            </div>
            {issue.after_photos.length > 0 ? (
              <div className="grid gap-2">
                <h2 className="font-semibold">{t("after")}</h2>
                <PhotoGallery
                  media={asMedia(issue.after_photos)}
                  label={t("afterOf", { reference: issue.reference })}
                />
              </div>
            ) : null}
          </Card>

          <Card className="grid gap-3 p-5">
            <h2 className="font-semibold">{t("location")}</h2>
            <div className="h-48 overflow-hidden rounded-lg border border-border">
              <PinMap
                center={point}
                zoom={15}
                pin={point}
                static
                label={t("mapLabel")}
                pinLabel={t("location")}
              />
            </div>
            <p className="flex items-start gap-2 text-sm text-muted-foreground">
              <MapPin aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              {t("precision", { meters: issue.location.precision_m })}
            </p>
          </Card>
        </div>

        <Card className="grid content-start gap-4 p-5">
          <h2 className="font-semibold">{t("progress")}</h2>
          <PublicTimeline events={issue.timeline} />
        </Card>
      </div>
    </div>
  );
}

/** The public page of one issue. Params are unwrapped inside Suspense. */
export function PublicIssue({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useTranslations("track.detail");
  const tTrack = useTranslations("track");
  const errorMessage = useErrorMessage();
  const query = useQuery({
    queryKey: ["public", "issue", id],
    queryFn: ({ signal }) => getPublicIssue(id, signal),
    retry: (count, error) => !isApiError(error) && count < 2,
  });

  return (
    <div className="grid gap-5">
      <Link
        href="/track"
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
        isApiError(query.error, "not_found") ||
        isApiError(query.error, "validation_error") ? (
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
              {tTrack("retry")}
            </Button>
          </Alert>
        )
      ) : (
        <Body issue={query.data} />
      )}
    </div>
  );
}
