import { ClipboardList } from "lucide-react";
import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { Alert } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("field");
  return { title: t("title") };
}

export default function FieldHomePage() {
  const t = useTranslations("field");
  return (
    <div className="grid gap-6 motion-safe:animate-rise">
      <div className="grid gap-1">
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <p className="text-muted-foreground">{t("subtitle")}</p>
      </div>

      <Card className="grid justify-items-center gap-3 px-6 py-12 text-center">
        <span className="grid size-14 place-items-center rounded-2xl bg-secondary text-secondary-foreground">
          <ClipboardList aria-hidden="true" className="size-7" />
        </span>
        <h2 className="text-lg font-semibold">{t("emptyTitle")}</h2>
        <p className="max-w-sm text-muted-foreground">{t("emptyBody")}</p>
      </Card>

      <Alert variant="info" title={t("offlineTitle")}>
        {t("offlineBody")}
      </Alert>
    </div>
  );
}
