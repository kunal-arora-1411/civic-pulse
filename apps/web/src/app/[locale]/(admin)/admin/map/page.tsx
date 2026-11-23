import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { MapScreen } from "@/components/admin/map/map-screen";
import { RequireAdminAccess } from "@/components/auth/guards";
import { PageLoading } from "@/components/page-loading";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.map");
  return { title: t("title") };
}

export default function AdminMapPage() {
  return (
    <RequireAdminAccess permission="issue:read">
      <Suspense fallback={<PageLoading />}>
        <MapScreen />
      </Suspense>
    </RequireAdminAccess>
  );
}
