import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { RequireAuth } from "@/components/auth/guards";
import { NotificationsScreen } from "@/components/notifications/notifications-screen";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("notifications");
  return { title: t("title"), robots: { index: false } };
}

export default function NotificationsPage() {
  const t = useTranslations("notifications");
  return (
    <main
      id="main"
      className="mx-auto grid w-full max-w-3xl flex-1 content-start gap-6 px-5 py-6 sm:px-8 sm:py-10"
    >
      <div className="grid gap-1">
        <h1 className="text-2xl font-semibold sm:text-3xl">{t("title")}</h1>
        <p className="text-muted-foreground">{t("description")}</p>
      </div>
      <RequireAuth>
        <NotificationsScreen />
      </RequireAuth>
    </main>
  );
}
