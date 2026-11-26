"use client";

import { AlarmClock, Hourglass } from "lucide-react";
import { useFormatter, useNow, useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import type { SlaState } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Flags an issue that is past its SLA deadline or close to it (FR-057).
 * Nothing shows while an issue is on track or has no target, so the
 * badge stands out in a long queue. The word and icon carry the meaning;
 * colour only reinforces it.
 */
export function SlaBadge({
  state,
  dueAt,
  className,
}: {
  state: SlaState;
  dueAt: string | null | undefined;
  className?: string;
}) {
  const t = useTranslations("sla");
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });
  if (!dueAt || (state !== "overdue" && state !== "due_soon")) return null;
  const due = new Date(dueAt);
  const overdue = state === "overdue";
  const Icon = overdue ? AlarmClock : Hourglass;
  return (
    <Badge
      variant={overdue ? "destructive" : "warning"}
      className={cn("whitespace-nowrap", className)}
      title={t("dueAt", {
        date: format.dateTime(due, { dateStyle: "medium", timeStyle: "short" }),
      })}
    >
      <Icon aria-hidden="true" />
      {overdue ? t("overdue") : t("dueSoon")}
      <span aria-hidden="true">·</span>
      <time dateTime={dueAt}>{format.relativeTime(due, now)}</time>
    </Badge>
  );
}
