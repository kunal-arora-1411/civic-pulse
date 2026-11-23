import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { IssuesScreen } from "@/components/admin/issues/issues-screen";
import { RequireAdminAccess } from "@/components/auth/guards";
import { PageLoading } from "@/components/page-loading";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.issues");
  return { title: t("title") };
}

export default function AdminIssuesPage() {
  return (
    <RequireAdminAccess permission="issue:read">
      {/* The filters live in the URL; useSearchParams() needs a boundary. */}
      <Suspense fallback={<PageLoading />}>
        <IssuesScreen />
      </Suspense>
    </RequireAdminAccess>
  );
}
