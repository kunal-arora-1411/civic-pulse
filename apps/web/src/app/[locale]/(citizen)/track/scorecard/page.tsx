import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import {
  ScorecardScreen,
  ScorecardSkeleton,
} from "@/components/track/scorecard";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("track.scorecard");
  return { title: t("metaTitle"), description: t("description") };
}

export default function ScorecardPage() {
  const t = useTranslations("track.scorecard");
  return (
    <main
      id="main"
      className="mx-auto grid w-full max-w-5xl flex-1 grid-cols-[minmax(0,1fr)] content-start gap-6 px-5 py-6 sm:px-8 sm:py-10"
    >
      <div className="grid gap-1">
        <h1 className="text-2xl font-semibold sm:text-3xl">{t("title")}</h1>
        <p className="max-w-2xl text-muted-foreground">{t("description")}</p>
      </div>
      <Suspense fallback={<ScorecardSkeleton />}>
        <ScorecardScreen />
      </Suspense>
    </main>
  );
}
