"use client";

import { Globe, Lock, MessageSquareText } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { STATUS_STYLE } from "@/components/issues/status-badge";
import { Badge } from "@/components/ui/badge";
import type { IssueTimelineEvent } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The full staff history, newest first. Internal entries are marked with
 * a lock and "Internal", public ones with a globe and "Visible to the
 * public", so the distinction never rests on colour (PRD §9.2: keep
 * internal notes separate from public updates).
 */
export function IssueTimeline({ events }: { events: IssueTimelineEvent[] }) {
  const t = useTranslations("admin.issueDetail.timeline");
  const tStatus = useTranslations("issueStatus");
  const format = useFormatter();
  const sorted = [...events].sort((a, b) => b.at.localeCompare(a.at));

  return (
    <ol className="grid gap-3">
      {sorted.map((event) => {
        const internal = event.visibility === "internal";
        const Icon = event.to_status
          ? STATUS_STYLE[event.to_status].icon
          : MessageSquareText;
        const title =
          event.type === "created"
            ? tStatus("reported")
            : event.to_status
              ? event.from_status
                ? t("changed", {
                    from: tStatus(event.from_status),
                    to: tStatus(event.to_status),
                  })
                : t("set", { to: tStatus(event.to_status) })
              : t("note");
        return (
          <li
            key={event.id}
            className={cn(
              "grid gap-2 rounded-lg border p-3",
              internal
                ? "border-dashed border-warning-soft-foreground/30 bg-warning-soft/40"
                : "border-border bg-card",
            )}
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <p className="flex items-center gap-2 font-semibold">
                <Icon aria-hidden="true" className="size-4 shrink-0" />
                {title}
              </p>
              <Badge variant={internal ? "warning" : "outline"}>
                {internal ? (
                  <Lock aria-hidden="true" />
                ) : (
                  <Globe aria-hidden="true" />
                )}
                {internal ? t("internal") : t("public")}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground">
              {event.actor?.display_name ?? t("system")} ·{" "}
              <time dateTime={event.at}>
                {format.dateTime(new Date(event.at), {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
              </time>
            </p>
            {event.reason ? (
              <div className="text-sm">
                <p className="text-xs font-semibold text-muted-foreground">
                  {t("reason")}
                </p>
                <p className="whitespace-pre-line">{event.reason}</p>
              </div>
            ) : null}
            {event.public_note ? (
              <div className="text-sm">
                <p className="flex items-center gap-1 text-xs font-semibold text-muted-foreground">
                  <Globe aria-hidden="true" className="size-3" />
                  {t("publicNote")}
                </p>
                <p className="whitespace-pre-line">{event.public_note}</p>
              </div>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
