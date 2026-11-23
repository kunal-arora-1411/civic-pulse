import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { IssueDetailScreen } from "@/components/admin/issues/issue-detail-screen";
import { RequireAdminAccess } from "@/components/auth/guards";
import { PageLoading } from "@/components/page-loading";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.issueDetail");
  return { title: t("metaTitle") };
}

/** Same pattern as /reports/[id]: params are unwrapped in Suspense. */
export default function AdminIssueDetailPage({
  params,
}: PageProps<"/[locale]/admin/issues/[id]">) {
  return (
    <RequireAdminAccess permission="issue:read">
      <Suspense fallback={<PageLoading />}>
        <IssueDetailScreen params={params} />
      </Suspense>
    </RequireAdminAccess>
  );
}
