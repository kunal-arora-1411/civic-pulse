import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

export type TableProps = ComponentProps<"table"> & {
  /**
   * Accessible name for the scroll container. On narrow screens the table
   * scrolls horizontally, and the container needs to be focusable (and so
   * named) for keyboard users to scroll it.
   */
  label: string;
  containerClassName?: string;
};

export function Table({
  className,
  containerClassName,
  label,
  ...props
}: TableProps) {
  return (
    <section
      aria-label={label}
      // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be keyboard reachable
      tabIndex={0}
      className={cn(
        "relative w-full overflow-x-auto rounded-2xl border border-border bg-card shadow-card",
        containerClassName,
      )}
    >
      <table
        className={cn(
          "w-full caption-bottom border-collapse text-sm",
          className,
        )}
        {...props}
      />
    </section>
  );
}

export function TableHeader({ className, ...props }: ComponentProps<"thead">) {
  return (
    <thead
      className={cn("bg-muted/50 [&_tr]:border-b", className)}
      {...props}
    />
  );
}

export function TableBody({ className, ...props }: ComponentProps<"tbody">) {
  return (
    <tbody className={cn("[&_tr:last-child]:border-0", className)} {...props} />
  );
}

export function TableRow({ className, ...props }: ComponentProps<"tr">) {
  return (
    <tr
      className={cn(
        "border-b border-border transition-colors hover:bg-muted/40",
        className,
      )}
      {...props}
    />
  );
}

export function TableHead({ className, ...props }: ComponentProps<"th">) {
  return (
    <th
      scope="col"
      className={cn(
        "h-10 whitespace-nowrap px-4 text-start align-middle font-mono text-[0.6875rem] font-medium uppercase tracking-[0.08em] text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

export function TableCell({ className, ...props }: ComponentProps<"td">) {
  return <td className={cn("px-4 py-3 align-middle", className)} {...props} />;
}

export function TableCaption({
  className,
  ...props
}: ComponentProps<"caption">) {
  return (
    <caption
      className={cn("px-4 py-3 text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}
