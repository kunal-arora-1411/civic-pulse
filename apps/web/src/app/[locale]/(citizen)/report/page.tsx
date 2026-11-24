import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { RequireAuth } from "@/components/auth/guards";
import { ReportFlow } from "@/components/report/report-flow";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("report");
  return { title: t("metaTitle"), robots: { index: false } };
}

export default function ReportPage() {
  const t = useTranslations("report");
  return (
    <main
      id="main"
      className="mx-auto grid w-full max-w-2xl flex-1 content-start gap-8 px-4 pt-8 pb-4 sm:px-6 sm:pt-14"
    >
      <h1 className="text-3xl font-semibold tracking-tight sm:text-5xl">
        {t("title")}
      </h1>
      <RequireAuth>
        <ReportFlow />
      </RequireAuth>
    </main>
  );
}
