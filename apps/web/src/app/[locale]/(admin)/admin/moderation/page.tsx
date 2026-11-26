import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { ModerationScreen } from "@/components/admin/moderation/moderation-screen";
import { RequireAdminAccess } from "@/components/auth/guards";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.moderation");
  return { title: t("title") };
}

export default function ModerationPage() {
  return (
    <RequireAdminAccess permission="issue:update">
      <ModerationScreen />
    </RequireAdminAccess>
  );
}
