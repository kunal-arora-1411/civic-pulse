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
      className="flex flex-1 flex-col items-center justify-center gap-10 px-6 py-16 text-center"
    >
      <Logo />
      <div className="grid max-w-lg justify-items-center gap-4">
        <p
          aria-hidden="true"
          className="text-brand-gradient font-display text-[7rem] leading-none font-bold tracking-tighter sm:text-[10rem]"
        >
          404
        </p>
        <h1 className="flex items-center gap-2 text-3xl font-semibold tracking-tight sm:text-4xl">
          <MapPinOff
            aria-hidden="true"
            className="size-7 shrink-0 text-primary"
          />
          {t("notFound.title")}
        </h1>
        <p className="text-lg text-muted-foreground">
          {t("notFound.description")}
        </p>
      </div>
      <Link href="/" className={buttonVariants({ variant: "ink" })}>
        {t("common.backHome")}
      </Link>
    </main>
  );
}
