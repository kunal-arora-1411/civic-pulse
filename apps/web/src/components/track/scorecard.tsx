"use client";

import { ArrowLeft } from "lucide-react";
import { useTranslations } from "next-intl";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useErrorMessage } from "@/hooks/use-error-message";
import { Link } from "@/i18n/navigation";
import type { WardScore } from "@/lib/api";
import { usePublicScorecard } from "./track-screen";

const OPEN_BAR = "bg-warning-soft-foreground/80";
const RESOLVED_BAR = "bg-success-soft-foreground/80";

export function ScorecardSkeleton() {
  return (
    <div className="grid gap-3">
      <Skeleton className="h-20 rounded-xl" />
      <Skeleton className="h-20 rounded-xl" />
      <Skeleton className="h-20 rounded-xl" />
    </div>
  );
}

function WardRow({ score, max }: { score: WardScore; max: number }) {
  const t = useTranslations("track.scorecard");
  const width = (value: number) => `${max > 0 ? (value / max) * 100 : 0}%`;
  const median = score.median_resolution_days;

  return (
    <li className="grid gap-2 py-4 first:pt-0 last:pb-0 sm:grid-cols-[12rem_minmax(0,1fr)_10rem] sm:items-center sm:gap-4">
      <h3 className="font-semibold">{score.ward.name}</h3>
      <div className="grid gap-1.5">
        {/* The numbers are in the text beside; the bars are decoration. */}
        <div
          aria-hidden="true"
          className="flex h-3 overflow-hidden rounded-full bg-muted"
        >
          <span
            className={OPEN_BAR}
            style={{ width: width(score.open_count) }}
          />
          <span
            className={RESOLVED_BAR}
            style={{ width: width(score.resolved_count) }}
          />
        </div>
        <p className="flex flex-wrap gap-x-4 text-sm">
          <span>
            <span className="text-muted-foreground">{t("open")}: </span>
            <span className="font-semibold tabular-nums">
              {score.open_count}
            </span>
          </span>
          <span>
            <span className="text-muted-foreground">{t("resolved")}: </span>
            <span className="font-semibold tabular-nums">
              {score.resolved_count}
            </span>
          </span>
        </p>
      </div>
      <p className="text-sm">
        <span className="block text-muted-foreground">{t("median")}</span>
        <span className="font-semibold tabular-nums">
          {median === null
            ? t("noMedian")
            : t("days", { count: Math.round(median * 10) / 10 })}
        </span>
      </p>
    </li>
  );
}

/** Per ward: open and resolved issues as bars, and the median days to fix. */
export function ScorecardScreen() {
  const t = useTranslations("track.scorecard");
  const errorMessage = useErrorMessage();
  const query = usePublicScorecard();
  const wards = query.data?.wards ?? [];
  const max = Math.max(
    0,
    ...wards.map((ward) => ward.open_count + ward.resolved_count),
  );

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
          <ScorecardSkeleton />
        </>
      ) : query.isError ? (
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
      ) : wards.length === 0 ? (
        <p className="text-muted-foreground">{t("empty")}</p>
      ) : (
        <Card className="grid gap-4 p-5">
          <ul
            aria-hidden="true"
            className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted-foreground"
          >
            <li className="inline-flex items-center gap-1.5">
              <span className={`size-3 rounded-sm ${OPEN_BAR}`} />
              {t("open")}
            </li>
            <li className="inline-flex items-center gap-1.5">
              <span className={`size-3 rounded-sm ${RESOLVED_BAR}`} />
              {t("resolved")}
            </li>
          </ul>
          <ul className="grid divide-y divide-border">
            {wards.map((score) => (
              <WardRow key={score.ward.id} score={score} max={max} />
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
