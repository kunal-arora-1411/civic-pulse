import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { MatchingSettings } from "@/components/admin/settings/matching-settings";
import { RequireAdminAccess } from "@/components/auth/guards";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.settings.matching");
  return { title: t("title") };
}

export default function MatchingSettingsPage() {
  return (
    <RequireAdminAccess permission="config:read">
      <MatchingSettings />
    </RequireAdminAccess>
  );
}
