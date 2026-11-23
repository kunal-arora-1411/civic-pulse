import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { AuditScreen } from "@/components/admin/audit/audit-screen";
import { RequirePermission } from "@/components/auth/guards";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.audit");
  return { title: t("title") };
}

export default function AdminAuditPage() {
  return (
    <RequirePermission permission="audit:read">
      <AuditScreen />
    </RequirePermission>
  );
}
