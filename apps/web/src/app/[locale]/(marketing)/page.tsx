import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { Bento } from "@/components/landing/bento";
import { CtaBanner, ForCities } from "@/components/landing/for-cities";
import { Hero } from "@/components/landing/hero";
import { LiveMap } from "@/components/landing/live-map";
import { RecentReportsStrip } from "@/components/landing/session-parts";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("landing");
  return { title: { absolute: `CivicPulse · ${t("metaTitle")}` } };
}

export default function LandingPage() {
  return (
    <main id="main" className="flex-1">
      <Hero />
      <Suspense fallback={null}>
        <RecentReportsStrip />
      </Suspense>
      <LiveMap />
      <Bento />
      <ForCities />
      <CtaBanner />
    </main>
  );
}
