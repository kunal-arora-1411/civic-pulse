import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * A KPI tile in the marketing site's style: mono label, large number, a
 * short hint below. The label is the accessible name of the number, so
 * the figure never stands alone.
 */
export function Stat({
  label,
  value,
  hint,
  tone = "neutral",
  className,
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "neutral" | "primary" | "warning" | "destructive";
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid content-between gap-6 rounded-2xl border border-border bg-card p-5 shadow-card",
        className,
      )}
    >
      <p className="eyebrow">{label}</p>
      <div className="grid gap-1">
        {/* A div, not a p: while loading, the value is a Skeleton div. */}
        <div
          className={cn(
            "font-display text-4xl font-semibold tracking-tight tabular-nums",
            tone === "primary" && "text-primary",
            tone === "warning" && "text-warning-soft-foreground",
            tone === "destructive" && "text-destructive",
          )}
        >
          {value}
        </div>
        {hint ? (
          <p className="font-mono text-xs text-muted-foreground">{hint}</p>
        ) : null}
      </div>
    </div>
  );
}
