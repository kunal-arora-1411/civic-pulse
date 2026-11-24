import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { RequireAuth } from "@/components/auth/guards";
import {
  DetailSkeleton,
  ReportDetail,
} from "@/components/citizen/report-detail";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("reports.detail");
  return { title: t("metaTitle"), robots: { index: false } };
}

/*
 * The id is only known at request time, so with Cache Components reading
 * it is runtime data. The page passes the params promise down instead of
 * awaiting it, and the client component unwraps it with use() inside
 * Suspense. The static shell then carries the header, footer and a
 * skeleton, and the report itself loads in the browser like every other
 * signed-in page.
 */
export default function ReportDetailPage({
  params,
}: PageProps<"/[locale]/reports/[id]">) {
  return (
    <main
      id="main"
      className="mx-auto w-full max-w-5xl flex-1 px-5 py-6 sm:px-8 sm:py-10"
    >
      <RequireAuth>
        <Suspense fallback={<DetailSkeleton />}>
          <ReportDetail params={params} />
        </Suspense>
      </RequireAuth>
    </main>
  );
}
