import { useTranslations } from "next-intl";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** Placeholder for a page body while the session or data loads. */
export function PageLoading({ className }: { className?: string }) {
  const t = useTranslations("common");
  return (
    <div className={cn("grid gap-4", className)}>
      <output className="sr-only">{t("loading")}</output>
      <Skeleton className="h-8 w-2/5" />
      <Skeleton className="h-4 w-3/5" />
      <div className="mt-2 grid gap-3">
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
      </div>
    </div>
  );
}
