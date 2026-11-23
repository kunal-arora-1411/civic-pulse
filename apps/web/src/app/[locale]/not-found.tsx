import { MapPinOff } from "lucide-react";
import { useTranslations } from "next-intl";
import { Logo } from "@/components/brand/logo";
import { buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";

export default function NotFound() {
  const t = useTranslations();
  return (
    <main
      id="main"
      className="bg-survey-grid flex flex-1 flex-col items-center justify-center gap-8 px-6 py-16 text-center"
    >
      <Logo />
      <div className="grid max-w-md justify-items-center gap-3">
        <MapPinOff aria-hidden="true" className="size-10 text-primary" />
        <h1 className="text-3xl font-semibold">{t("notFound.title")}</h1>
        <p className="text-muted-foreground">{t("notFound.description")}</p>
      </div>
      <Link href="/" className={buttonVariants({ variant: "outline" })}>
        {t("common.backHome")}
      </Link>
    </main>
  );
}
