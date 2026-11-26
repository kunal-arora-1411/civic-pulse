import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { DetailSkeleton } from "@/components/citizen/report-detail";
import { PublicIssue } from "@/components/track/public-issue";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("track.detail");
  return { title: t("metaTitle") };
}

/*
 * The id is runtime data under Cache Components: the params promise is
 * passed down and unwrapped with use() inside Suspense, so the static
 * shell carries the layout and a skeleton.
 */
export default function PublicIssuePage({
  params,
}: PageProps<"/[locale]/track/[id]">) {
  return (
    <main
      id="main"
      className="mx-auto w-full max-w-5xl flex-1 px-5 py-6 sm:px-8 sm:py-10"
    >
      <Suspense fallback={<DetailSkeleton />}>
        <PublicIssue params={params} />
      </Suspense>
    </main>
  );
}
