import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { PublicAnnouncements } from "@/components/track/announcements";
import {
  ScorecardLink,
  TrackScreen,
  TrackSkeleton,
} from "@/components/track/track-screen";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("track");
  return { title: t("metaTitle"), description: t("metaDescription") };
}

/** The public tracker: no sign-in, everything loads in the browser. */
export default function TrackPage() {
  const t = useTranslations("track");
  return (
    <main
      id="main"
      className="mx-auto grid w-full max-w-[1200px] flex-1 grid-cols-[minmax(0,1fr)] content-start gap-6 px-5 py-6 sm:px-8 sm:py-10"
    >
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="grid gap-1">
          <h1 className="text-2xl font-semibold sm:text-3xl">{t("title")}</h1>
          <p className="max-w-2xl text-muted-foreground">{t("description")}</p>
        </div>
        <ScorecardLink />
      </div>
      <PublicAnnouncements />
      <Suspense fallback={<TrackSkeleton />}>
        <TrackScreen />
      </Suspense>
    </main>
  );
}
