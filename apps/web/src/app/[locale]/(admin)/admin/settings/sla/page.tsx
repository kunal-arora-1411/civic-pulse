import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { SlaSettings } from "@/components/admin/settings/sla-settings";
import { RequireAdminAccess } from "@/components/auth/guards";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.settings.sla");
  return { title: t("title") };
}

export default function SlaSettingsPage() {
  return (
    <RequireAdminAccess permission="config:read">
      <SlaSettings />
    </RequireAdminAccess>
  );
}
