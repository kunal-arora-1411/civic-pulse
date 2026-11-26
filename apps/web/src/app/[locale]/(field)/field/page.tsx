import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { RequireFieldAccess } from "@/components/auth/guards";
import { WorkOrderList } from "@/components/field/work-order-list";
import { Alert } from "@/components/ui/alert";

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

        <WorkOrderList />

        <Alert variant="info" title={t("offlineTitle")}>
          {t("offlineBody")}
        </Alert>
      </div>
    </RequireFieldAccess>
  );
}
