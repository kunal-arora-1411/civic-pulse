import { cva, type VariantProps } from "class-variance-authority";
import {
  CircleAlert,
  CircleCheck,
  Info,
  type LucideIcon,
  TriangleAlert,
} from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/utils";

const alertVariants = cva(
  "flex gap-3 rounded-2xl border p-4 text-sm [&>svg]:mt-0.5 [&>svg]:size-5 [&>svg]:shrink-0",
  {
    variants: {
      variant: {
        info: "border-info-soft-foreground/20 bg-info-soft text-info-soft-foreground",
        success:
          "border-success-soft-foreground/20 bg-success-soft text-success-soft-foreground",
        warning:
          "border-warning-soft-foreground/25 bg-warning-soft text-warning-soft-foreground",
        destructive:
          "border-destructive-soft-foreground/25 bg-destructive-soft text-destructive-soft-foreground",
      },
    },
    defaultVariants: { variant: "info" },
  },
);

const icons: Record<NonNullable<AlertProps["variant"]>, LucideIcon> = {
  info: Info,
  success: CircleCheck,
  warning: TriangleAlert,
  destructive: CircleAlert,
};

export type AlertProps = Omit<ComponentProps<"div">, "title"> &
  VariantProps<typeof alertVariants> & {
    title?: ReactNode;
    /**
     * `assertive` interrupts the screen reader (use for errors the user must
     * act on), `polite` waits for a pause, `off` renders a static message.
     */
    live?: "assertive" | "polite" | "off";
  };

/** An inline message. The icon and wording carry meaning, not just colour. */
export function Alert({
  className,
  variant = "info",
  title,
  live = "off",
  children,
  ...props
}: AlertProps) {
  const Icon = icons[variant ?? "info"];
  const role =
    live === "assertive" ? "alert" : live === "polite" ? "status" : undefined;
  return (
    <div
      role={role}
      className={cn(alertVariants({ variant }), className)}
      {...props}
    >
      <Icon aria-hidden="true" />
      <div className="grid gap-1">
        {title ? <p className="font-semibold leading-snug">{title}</p> : null}
        {children ? <div className="leading-relaxed">{children}</div> : null}
      </div>
    </div>
  );
}
