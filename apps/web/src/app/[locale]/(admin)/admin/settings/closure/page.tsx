import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { ClosureSettings } from "@/components/admin/settings/closure-settings";
import { RequireAdminAccess } from "@/components/auth/guards";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.settings.closure");
  return { title: t("title") };
}

export default function ClosureSettingsPage() {
  return (
    <RequireAdminAccess permission="config:read">
      <ClosureSettings />
    </RequireAdminAccess>
  );
}
