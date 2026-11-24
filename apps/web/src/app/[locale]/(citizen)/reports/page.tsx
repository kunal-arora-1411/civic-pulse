import { MapPinPlus } from "lucide-react";
import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { RequireAuth } from "@/components/auth/guards";
import { MyReportsScreen } from "@/components/citizen/my-reports-screen";
import { buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("reports");
  return { title: t("title"), robots: { index: false } };
}

export default function MyReportsPage() {
  const t = useTranslations("reports");
  return (
    <main
      id="main"
      className="mx-auto grid w-full max-w-3xl flex-1 content-start gap-8 px-4 py-8 sm:px-6 sm:py-14"
    >
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="grid gap-2">
          <h1 className="text-3xl font-semibold tracking-tight sm:text-5xl">
            {t("title")}
          </h1>
          <p className="max-w-md text-lg text-muted-foreground">
            {t("description")}
          </p>
        </div>
        <Link href="/report" className={buttonVariants({ variant: "ink" })}>
          <MapPinPlus aria-hidden="true" />
          {t("newReport")}
        </Link>
      </div>
      <RequireAuth>
        <MyReportsScreen />
      </RequireAuth>
    </main>
  );
}
