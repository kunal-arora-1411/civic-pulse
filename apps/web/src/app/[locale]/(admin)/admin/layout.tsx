import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { AdminShell } from "@/components/admin/admin-shell";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin");
  return {
    title: { default: t("metaTitle"), template: `%s · ${t("metaTitle")}` },
    // The console is useless to crawlers and shouldn't show up in search.
    robots: { index: false, follow: false },
  };
}

export default function AdminLayout({
  children,
}: LayoutProps<"/[locale]/admin">) {
  return <AdminShell>{children}</AdminShell>;
}
