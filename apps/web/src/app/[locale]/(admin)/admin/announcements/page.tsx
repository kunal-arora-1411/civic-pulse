import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { AnnouncementsScreen } from "@/components/admin/announcements/announcements-screen";
import { RequireAdminAccess } from "@/components/auth/guards";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.announcements");
  return { title: t("title") };
}

export default function AdminAnnouncementsPage() {
  return (
    <RequireAdminAccess permission="config:read">
      <AnnouncementsScreen />
    </RequireAdminAccess>
  );
}
