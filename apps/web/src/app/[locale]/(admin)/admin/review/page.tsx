import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { ReviewScreen } from "@/components/admin/review/review-screen";
import { RequireAdminAccess } from "@/components/auth/guards";
import { PageLoading } from "@/components/page-loading";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.review");
  return { title: t("title") };
}

export default function AdminReviewPage() {
  return (
    <RequireAdminAccess permission="issue:triage">
      {/* The task on screen is kept in ?task=; useSearchParams() needs a boundary. */}
      <Suspense fallback={<PageLoading />}>
        <ReviewScreen />
      </Suspense>
    </RequireAdminAccess>
  );
}
