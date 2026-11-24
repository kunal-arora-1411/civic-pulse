"use client";

import type { VariantProps } from "class-variance-authority";
import {
  ChevronDown,
  ChevronsUp,
  ChevronUp,
  Equal,
  type LucideIcon,
  Siren,
} from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { Badge, type badgeVariants } from "@/components/ui/badge";
import type { PriorityBand, SeverityLevel } from "@/lib/api";
import { cn } from "@/lib/utils";

type Variant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;

/**
 * Each band has its own icon and word as well as a colour, so the
 * priority reads the same without colour (PRD §9.1, §9.2). The icons rise
 * with urgency: one chevron down, level, one up, a siren.
 */
export const PRIORITY_STYLE: Record<
  PriorityBand,
  { icon: LucideIcon; variant: Variant }
> = {
  critical: { icon: Siren, variant: "destructive" },
  high: { icon: ChevronsUp, variant: "warning" },
  medium: { icon: Equal, variant: "info" },
  low: { icon: ChevronDown, variant: "neutral" },
};

export function PriorityBadge({
  band,
  score,
  overridden = false,
  className,
}: {
  band: PriorityBand;
  /** Shown after the band, e.g. "High · 67". */
  score?: number | null;
  /** Marks a band set by hand. */
  overridden?: boolean;
  className?: string;
}) {
  const t = useTranslations("priority");
  const format = useFormatter();
  const { icon: Icon, variant } = PRIORITY_STYLE[band];
  return (
    <Badge variant={variant} className={cn("tabular-nums", className)}>
      <Icon aria-hidden="true" />
      <span className="sr-only">{t("label")}: </span>
      {t(`band.${band}`)}
      {score !== undefined && score !== null ? (
        <>
          <span aria-hidden="true">·</span>
          <span className="sr-only">{t("score")}</span>
          {format.number(score, { maximumFractionDigits: 0 })}
        </>
      ) : null}
      {overridden ? (
        <span className="font-normal opacity-80">({t("manual")})</span>
      ) : null}
    </Badge>
  );
}

const SEVERITY_ICON: Record<SeverityLevel, LucideIcon> = {
  low: ChevronDown,
  medium: Equal,
  high: ChevronUp,
  critical: ChevronsUp,
};

export function SeverityBadge({
  level,
  overridden = false,
  className,
}: {
  level: SeverityLevel;
  overridden?: boolean;
  className?: string;
}) {
  const t = useTranslations("severity");
  const Icon = SEVERITY_ICON[level];
  return (
    <Badge variant="outline" className={className}>
      <Icon aria-hidden="true" />
      <span className="sr-only">{t("label")}: </span>
      {t(`level.${level}`)}
      {overridden ? (
        <span className="font-normal text-muted-foreground">
          ({t("manual")})
        </span>
      ) : null}
    </Badge>
  );
}
