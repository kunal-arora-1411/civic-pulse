import { MapPinPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

/**
 * The primary call to action. Signed-out visitors are sent to sign in by
 * the /report page itself and come straight back afterwards.
 */
export function ReportCta() {
  const t = useTranslations("citizen");
  return (
    <div className="grid w-full max-w-md gap-3 sm:max-w-none sm:grid-flow-col sm:items-center sm:justify-start sm:gap-4">
      <Link
        href="/report"
        className={cn(
          buttonVariants({ size: "lg" }),
          "h-14 px-7 text-lg [&_svg]:size-5",
        )}
      >
        <MapPinPlus aria-hidden="true" />
        {t("reportCta")}
      </Link>
      <p className="text-sm font-medium text-muted-foreground">
        {t("reportHint")}
      </p>
    </div>
  );
}
