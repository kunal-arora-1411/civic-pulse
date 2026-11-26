import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { AnalyticsScreen } from "@/components/admin/analytics/analytics-screen";
import { RequireAdminAccess } from "@/components/auth/guards";
import { PageLoading } from "@/components/page-loading";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.analytics");
  return { title: t("title") };
}

export default function AdminAnalyticsPage() {
  return (
    <RequireAdminAccess permission="analytics:read">
      {/* The filters live in the URL; useSearchParams() needs a boundary. */}
      <Suspense fallback={<PageLoading />}>
        <AnalyticsScreen />
      </Suspense>
    </RequireAdminAccess>
  );
}
