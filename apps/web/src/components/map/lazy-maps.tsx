"use client";

import { MapIcon } from "lucide-react";
import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** Shown while the map script loads, and in the static shell. */
export function MapSkeleton({ className }: { className?: string }) {
  const t = useTranslations("map");
  return (
    <div className={cn("relative size-full", className)}>
      <Skeleton className="absolute inset-0 rounded-xl" />
      <div className="absolute inset-0 grid place-items-center text-muted-foreground">
        <MapIcon aria-hidden="true" className="size-8 opacity-60" />
      </div>
      <output className="sr-only">{t("loading")}</output>
    </div>
  );
}

/*
 * Leaflet needs `window`, so maps load in the browser only. next/dynamic
 * with ssr: false has to be called from a Client Component, which is why
 * these wrappers live here. Each import becomes its own chunk, so pages
 * without a map never download Leaflet.
 */
export const PinMap = dynamic(
  () => import("./pin-map").then((mod) => mod.PinMap),
  { ssr: false, loading: () => <MapSkeleton /> },
);

export const ComparisonMap = dynamic(
  () => import("./comparison-map").then((mod) => mod.ComparisonMap),
  { ssr: false, loading: () => <MapSkeleton /> },
);

export const IssuesMap = dynamic(
  () => import("./issues-map").then((mod) => mod.IssuesMap),
  { ssr: false, loading: () => <MapSkeleton /> },
);
