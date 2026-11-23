import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

export const inputClasses = cn(
  "flex h-10 w-full min-w-0 rounded-lg border border-input bg-card px-3 text-[0.9375rem] text-foreground",
  "placeholder:text-muted-foreground transition-[border-color,box-shadow]",
  "focus-visible:border-ring focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/30",
  "disabled:cursor-not-allowed disabled:opacity-60",
  "aria-invalid:border-destructive aria-invalid:focus-visible:ring-destructive/30",
);

export function Input({
  className,
  type = "text",
  ...props
}: ComponentProps<"input">) {
  return (
    <input type={type} className={cn(inputClasses, className)} {...props} />
  );
}
