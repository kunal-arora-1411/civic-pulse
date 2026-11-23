"use client";

import type { VariantProps } from "class-variance-authority";
import {
  Archive,
  BadgeCheck,
  CircleCheck,
  CircleDot,
  CircleX,
  Hammer,
  Hourglass,
  type LucideIcon,
  RotateCcw,
  ScanSearch,
  UserCheck,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { Badge, type badgeVariants } from "@/components/ui/badge";
import type { IssueStatus } from "@/lib/api";

type Variant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;

/**
 * Each status has its own icon as well as a colour and a label, so the
 * status reads the same for colour-blind users and in greyscale prints.
 */
export const STATUS_STYLE: Record<
  IssueStatus,
  { icon: LucideIcon; variant: Variant }
> = {
  reported: { icon: CircleDot, variant: "info" },
  under_review: { icon: ScanSearch, variant: "warning" },
  verified: { icon: BadgeCheck, variant: "primary" },
  assigned: { icon: UserCheck, variant: "primary" },
  in_progress: { icon: Hammer, variant: "warning" },
  pending_verification: { icon: Hourglass, variant: "warning" },
  resolved: { icon: CircleCheck, variant: "success" },
  rejected: { icon: CircleX, variant: "destructive" },
  closed: { icon: Archive, variant: "neutral" },
  reopened: { icon: RotateCcw, variant: "warning" },
};

export function StatusBadge({
  status,
  className,
}: {
  status: IssueStatus;
  className?: string;
}) {
  const t = useTranslations("issueStatus");
  const { icon: Icon, variant } = STATUS_STYLE[status];
  return (
    <Badge variant={variant} className={className}>
      <Icon aria-hidden="true" />
      {t(status)}
    </Badge>
  );
}
