import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

/** A loading indicator with a text alternative for assistive technology. */
export function Spinner({
  label,
  className,
}: {
  label: string;
  className?: string;
}) {
  return (
    <output className={cn("inline-flex items-center", className)}>
      <Loader2
        aria-hidden="true"
        className="size-5 text-muted-foreground motion-safe:animate-spin"
      />
      <span className="sr-only">{label}</span>
    </output>
  );
}
