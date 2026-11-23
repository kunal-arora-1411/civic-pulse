"use client";

import { Inbox } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import type { PublicTimelineEvent } from "@/lib/api";
import { cn } from "@/lib/utils";
import { STATUS_STYLE } from "./status-badge";

/**
 * The citizen-facing history of an issue: public events only (the API
 * never sends internal notes or staff names here), newest last so it
 * reads as a story.
 */
export function PublicTimeline({ events }: { events: PublicTimelineEvent[] }) {
  const t = useTranslations("timeline");
  const tStatus = useTranslations("issueStatus");
  const format = useFormatter();
  const sorted = [...events].sort((a, b) => a.at.localeCompare(b.at));

  return (
    <ol className="grid gap-0">
      {sorted.map((event, index) => {
        const status = event.to_status ?? null;
        const Icon = status ? STATUS_STYLE[status].icon : Inbox;
        const last = index === sorted.length - 1;
        const title =
          event.type === "created" ||
          (!event.from_status && status === "reported")
            ? tStatus("reported")
            : status
              ? t("statusChanged", { status: tStatus(status) })
              : t("update");
        return (
          <li
            key={`${event.at}-${index}`}
            className="relative flex gap-3 pb-6 last:pb-0"
          >
            {last ? null : (
              <span
                aria-hidden="true"
                className="absolute start-4 top-9 bottom-1 w-px -translate-x-1/2 bg-border rtl:translate-x-1/2"
              />
            )}
            <span
              className={cn(
                "relative grid size-8 shrink-0 place-items-center rounded-full border",
                last
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-muted-foreground",
              )}
            >
              <Icon aria-hidden="true" className="size-4" />
            </span>
            <div className="grid gap-1 pt-1">
              <p className="font-semibold leading-tight">{title}</p>
              <p className="text-sm text-muted-foreground">
                <time dateTime={event.at}>
                  {format.dateTime(new Date(event.at), {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                </time>
              </p>
              {event.public_note ? (
                <blockquote className="mt-1 rounded-lg border-s-4 border-primary/40 bg-muted/60 px-3 py-2 text-sm">
                  <span className="sr-only">{t("noteFromCity")}: </span>
                  {event.public_note}
                </blockquote>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
