import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

/** Decorative placeholder. Pair it with a visually hidden loading message. */
export function Skeleton({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "rounded-md bg-muted bg-[linear-gradient(90deg,transparent,color-mix(in_oklch,var(--card)_70%,transparent),transparent)] bg-size-[200%_100%] motion-safe:animate-shimmer",
        className,
      )}
      {...props}
    />
  );
}
