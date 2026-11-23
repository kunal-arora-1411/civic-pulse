import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

export type LabelProps = ComponentProps<"label"> & {
  /** Adds a visual marker. Pair it with `required` on the control itself. */
  required?: boolean;
};

export function Label({
  className,
  required,
  children,
  htmlFor,
  ...props
}: LabelProps) {
  return (
    <label
      htmlFor={htmlFor}
      className={cn(
        "text-sm font-semibold leading-none text-foreground",
        className,
      )}
      {...props}
    >
      {children}
      {required ? (
        <span aria-hidden="true" className="ms-0.5 text-destructive">
          *
        </span>
      ) : null}
    </label>
  );
}
