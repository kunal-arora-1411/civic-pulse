"use client";

import { ChevronRight, MapPin } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { CategoryIcon } from "@/components/issues/category-icon";
import { StatusBadge } from "@/components/issues/status-badge";
import { RemoteImage } from "@/components/media/remote-image";
import { Skeleton } from "@/components/ui/skeleton";
import { useLocalized } from "@/hooks/use-reference-data";
import { Link } from "@/i18n/navigation";
import type { MyReport } from "@/lib/api";

export function ReportCard({ report }: { report: MyReport }) {
  const t = useTranslations("reports");
  const format = useFormatter();
  const localized = useLocalized();
  const category = localized(report.category.name_i18n);

  return (
    <Link
      href={`/reports/${report.id}`}
      className="group flex gap-3 rounded-xl border border-border bg-card p-3 shadow-card transition-shadow hover:shadow-raised sm:gap-4 sm:p-4"
    >
      <RemoteImage
        src={report.thumb_url}
        alt=""
        width={96}
        height={96}
        className="size-20 shrink-0 rounded-lg sm:size-24"
      />
      <div className="grid min-w-0 flex-1 content-start gap-1.5">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <p className="flex min-w-0 items-center gap-1.5 font-semibold">
            <CategoryIcon
              icon={report.category.icon}
              className="size-4 shrink-0 text-primary"
            />
            <span className="truncate">{category}</span>
          </p>
          <StatusBadge status={report.issue.status} />
        </div>
        <p className="flex items-start gap-1.5 text-sm text-muted-foreground">
          <MapPin aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
          <span className="line-clamp-2">
            {report.address_text || t("noAddress")}
          </span>
        </p>
        <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
          <span className="font-mono font-medium text-foreground">
            {report.reference}
          </span>
          <span aria-hidden="true">·</span>
          <time dateTime={report.created_at}>
            {format.dateTime(new Date(report.created_at), {
              dateStyle: "medium",
            })}
          </time>
        </p>
      </div>
      <ChevronRight
        aria-hidden="true"
        className="hidden size-5 shrink-0 self-center text-muted-foreground transition-transform group-hover:translate-x-0.5 sm:block rtl:rotate-180"
      />
    </Link>
  );
}

export function ReportCardSkeleton() {
  return (
    <div className="flex gap-3 rounded-xl border border-border bg-card p-3 sm:gap-4 sm:p-4">
      <Skeleton className="size-20 shrink-0 rounded-lg sm:size-24" />
      <div className="grid flex-1 content-start gap-2">
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-3 w-1/3" />
      </div>
    </div>
  );
}
