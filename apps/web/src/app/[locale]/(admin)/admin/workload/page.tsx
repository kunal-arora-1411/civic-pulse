import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { WorkloadScreen } from "@/components/admin/workload/workload-screen";
import { RequireAdminAccess } from "@/components/auth/guards";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.workload");
  return { title: t("title") };
}

export default function WorkloadPage() {
  return (
    <RequireAdminAccess permission="issue:assign">
      <WorkloadScreen />
    </RequireAdminAccess>
  );
}
