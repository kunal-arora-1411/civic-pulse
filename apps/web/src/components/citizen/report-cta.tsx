import { Clock, MapPinPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * The primary call to action. Reporting ships in Phase 1, so for now the
 * button is present but inert. It uses aria-disabled rather than
 * `disabled` so it stays focusable and screen readers still reach the
 * "coming soon" explanation it points to.
 */
export function ReportCta() {
  const t = useTranslations("citizen");
  return (
    <div className="grid w-full max-w-md gap-3 sm:max-w-none sm:grid-flow-col sm:justify-start sm:items-center sm:gap-4">
      <button
        type="button"
        aria-disabled="true"
        aria-describedby="report-coming-soon"
        className={cn(
          buttonVariants({ size: "lg" }),
          "h-14 cursor-not-allowed px-7 text-lg opacity-100 aria-disabled:pointer-events-auto aria-disabled:opacity-70 [&_svg]:size-5",
        )}
      >
        <MapPinPlus aria-hidden="true" />
        {t("reportCta")}
      </button>
      <p
        id="report-coming-soon"
        className="flex items-center gap-2 text-sm font-medium text-muted-foreground"
      >
        <Clock aria-hidden="true" className="size-4 shrink-0" />
        {t("reportComingSoon")}
      </p>
    </div>
  );
}
