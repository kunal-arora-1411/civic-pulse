"use client";

import {
  Ban,
  CircleCheckBig,
  CircleDashed,
  Hammer,
  Hourglass,
  type LucideIcon,
  ThumbsUp,
  Undo2,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import type { WorkOrderState } from "@/lib/api";

type BadgeVariant =
  | "neutral"
  | "primary"
  | "success"
  | "warning"
  | "destructive"
  | "info";

export const WORK_ORDER_STYLE: Record<
  WorkOrderState,
  { icon: LucideIcon; variant: BadgeVariant }
> = {
  pending_acceptance: { icon: CircleDashed, variant: "warning" },
  accepted: { icon: ThumbsUp, variant: "info" },
  in_progress: { icon: Hammer, variant: "primary" },
  completion_requested: { icon: Hourglass, variant: "info" },
  done: { icon: CircleCheckBig, variant: "success" },
  declined: { icon: Undo2, variant: "neutral" },
  cancelled: { icon: Ban, variant: "neutral" },
};

/** Text and an icon, never colour alone. */
export function WorkOrderStateBadge({
  state,
  className,
}: {
  state: WorkOrderState;
  className?: string;
}) {
  const t = useTranslations("workOrderState");
  const { icon: Icon, variant } = WORK_ORDER_STYLE[state];
  return (
    <Badge variant={variant} className={className}>
      <Icon aria-hidden="true" />
      {t(state)}
    </Badge>
  );
}
