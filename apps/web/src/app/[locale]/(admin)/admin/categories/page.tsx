import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { CategoriesScreen } from "@/components/admin/categories/categories-screen";
import { RequireAdminAccess } from "@/components/auth/guards";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.categories");
  return { title: t("title") };
}

export default function AdminCategoriesPage() {
  return (
    <RequireAdminAccess permission="config:read">
      <CategoriesScreen />
    </RequireAdminAccess>
  );
}
