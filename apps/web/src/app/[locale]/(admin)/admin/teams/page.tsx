import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { TeamsScreen } from "@/components/admin/teams/teams-screen";
import { RequireAdminAccess } from "@/components/auth/guards";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.teams");
  return { title: t("title") };
}

export default function TeamsPage() {
  return (
    <RequireAdminAccess permission="config:read">
      <TeamsScreen />
    </RequireAdminAccess>
  );
}
