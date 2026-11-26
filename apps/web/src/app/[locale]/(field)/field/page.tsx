import { ClipboardList } from "lucide-react";
import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { RequireFieldAccess } from "@/components/auth/guards";
import { Alert } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("field");
  return { title: t("title") };
}

export default function FieldHomePage() {
  const t = useTranslations("field");
  // The guard lives here, not in the field layout, so the layout always
  // renders this segment (see AdminShell for why that matters).
  return (
    <RequireFieldAccess>
      <div className="grid gap-6 motion-safe:animate-rise">
        <div className="grid gap-2">
          <p className="eyebrow">{t("badge")}</p>
          <h1 className="text-3xl font-semibold tracking-tight">
            {t("title")}
          </h1>
          <p className="text-muted-foreground">{t("subtitle")}</p>
        </div>

        <Card className="relative grid justify-items-center gap-3 overflow-hidden px-6 py-14 text-center">
          <div
            aria-hidden="true"
            className="bg-survey-grid absolute inset-0 [mask-image:radial-gradient(ellipse_at_center,black,transparent_70%)]"
          />
          <span className="bg-brand-gradient relative grid size-16 place-items-center rounded-2xl text-white shadow-raised">
            <ClipboardList aria-hidden="true" className="size-7" />
          </span>
          <h2 className="relative text-xl font-semibold tracking-tight">
            {t("emptyTitle")}
          </h2>
          <p className="relative max-w-sm text-muted-foreground">
            {t("emptyBody")}
          </p>
        </Card>

        <Alert variant="info" title={t("offlineTitle")}>
          {t("offlineBody")}
        </Alert>
      </div>
    </RequireFieldAccess>
  );
}
