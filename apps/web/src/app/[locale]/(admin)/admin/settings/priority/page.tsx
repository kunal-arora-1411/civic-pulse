import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { PrioritySettings } from "@/components/admin/settings/priority-settings";
import { RequireAdminAccess } from "@/components/auth/guards";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.settings.priority");
  return { title: t("title") };
}

export default function PrioritySettingsPage() {
  return (
    <RequireAdminAccess permission="config:read">
      <PrioritySettings />
    </RequireAdminAccess>
  );
}
