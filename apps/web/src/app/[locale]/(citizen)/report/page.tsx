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
      className="mx-auto grid w-full max-w-4xl flex-1 grid-cols-[minmax(0,1fr)] content-start gap-6 px-5 pt-6 pb-4 sm:px-8 sm:pt-10"
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
