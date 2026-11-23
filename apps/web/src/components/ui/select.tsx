import { ChevronDown } from "lucide-react";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";
import { inputClasses } from "./input";

/**
 * A styled native select. Native controls give us the platform picker on
 * mobile, full keyboard support and screen reader semantics for free.
 */
export function Select({
  className,
  children,
  ...props
}: ComponentProps<"select">) {
  return (
    <div className={cn("relative", className)}>
      <select
        className={cn(inputClasses, "cursor-pointer appearance-none pe-9")}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        aria-hidden="true"
        className="pointer-events-none absolute end-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
      />
    </div>
  );
}
