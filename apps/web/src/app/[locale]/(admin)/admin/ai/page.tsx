import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { AiScreen } from "@/components/admin/settings/ai-screen";
import { RequireAdminAccess } from "@/components/auth/guards";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.ai");
  return { title: t("title") };
}

export default function AiPage() {
  return (
    <RequireAdminAccess permission="config:read">
      <AiScreen />
    </RequireAdminAccess>
  );
}
