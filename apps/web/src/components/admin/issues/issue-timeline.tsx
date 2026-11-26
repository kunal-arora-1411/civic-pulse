"use client";

import {
  Archive,
  ArrowRightFromLine,
  BadgeCheck,
  CircleX,
  Combine,
  Gauge,
  Globe,
  Hammer,
  Hand,
  Hourglass,
  Link2,
  Link2Off,
  Lock,
  type LucideIcon,
  Megaphone,
  MessageSquareText,
  NotebookPen,
  Repeat,
  RotateCcw,
  Split,
  Tags,
  ThumbsUp,
  TimerOff,
  Undo2,
  UserCheck,
  UserMinus,
  UserPlus,
  UserRoundCheck,
} from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { STATUS_STYLE } from "@/components/issues/status-badge";
import { Badge } from "@/components/ui/badge";
import type { IssueTimelineEvent } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Event types with their own wording and icon: Phase 2 (contract D.5),
 * SLA escalations and Phase 3 operations (contract "Timeline event types").
 * Anything else is drawn from its status change, or as a note.
 */
const PHASE2_EVENTS = {
  report_linked: UserPlus,
  merged: Combine,
  merged_into: ArrowRightFromLine,
  split: Split,
  category_changed: Tags,
  severity_changed: Gauge,
  priority_changed: Hand,
  related_added: Link2,
  related_removed: Link2Off,
  sla_breached: TimerOff,
  sla_escalated: Megaphone,
  assigned: UserCheck,
  reassigned: Repeat,
  work_order_accepted: ThumbsUp,
  work_order_declined: Undo2,
  work_started: Hammer,
  progress: NotebookPen,
  closure_requested: Hourglass,
  closure_approved: BadgeCheck,
  closure_rejected: CircleX,
  verification: UserRoundCheck,
  reopened: RotateCcw,
  closed: Archive,
  report_withdrawn: UserMinus,
} satisfies Record<string, LucideIcon>;

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function nameOf(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  return text(record.name) ?? text(record.display_name);
}

type Phase2Event = keyof typeof PHASE2_EVENTS;

function isPhase2Event(type: string): type is Phase2Event {
  return Object.hasOwn(PHASE2_EVENTS, type);
}

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
        const phase2 = isPhase2Event(event.type) ? event.type : null;
        const Icon = phase2
          ? PHASE2_EVENTS[phase2]
          : event.to_status
            ? STATUS_STYLE[event.to_status].icon
            : MessageSquareText;
        const title = phase2
          ? t(`types.${phase2}`)
          : event.type === "created"
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
            <EventDetail event={event} />
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

/** The one line of staff detail an operations event carries in `data`. */
function EventDetail({ event }: { event: IssueTimelineEvent }) {
  const t = useTranslations("admin.issueDetail.timeline");
  const data = event.data ?? {};
  let line: string | null = null;
  if (event.type === "assigned" || event.type === "reassigned") {
    const team = nameOf(data.team);
    const assignee = nameOf(data.assignee);
    if (team) {
      line = assignee
        ? t("assignedTo", { team, assignee })
        : t("assignedToTeam", { team });
    }
  } else if (event.type === "verification") {
    const outcome = data.outcome;
    if (outcome === "resolved" || outcome === "unresolved") {
      line = t(`verificationOutcome.${outcome}`);
    }
  }
  const note =
    event.type === "progress" ||
    event.type === "closure_requested" ||
    event.type === "verification" ||
    event.type === "assigned" ||
    event.type === "reassigned"
      ? text(data.note)
      : null;
  if (!line && !note) return null;
  return (
    <div className="grid gap-1 text-sm">
      {line ? <p>{line}</p> : null}
      {note ? <p className="whitespace-pre-line">{note}</p> : null}
    </div>
  );
}
