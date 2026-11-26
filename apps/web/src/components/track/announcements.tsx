"use client";

import { useQuery } from "@tanstack/react-query";
import { Construction, Info, type Megaphone, PlugZap } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useLocalized } from "@/hooks/use-reference-data";
import {
  type AnnouncementKind,
  listPublicAnnouncements,
  type PublicAnnouncement,
} from "@/lib/api";

const ICONS: Record<AnnouncementKind, typeof Megaphone> = {
  planned_works: Construction,
  outage: PlugZap,
  advisory: Info,
};

/**
 * Service announcements showing now (FR-087), above the public tracker.
 * Renders nothing when there are none, or when they can't be loaded: the
 * tracker itself matters more than its notices.
 */
export function PublicAnnouncements() {
  const t = useTranslations("track.announcements");
  const query = useQuery({
    queryKey: ["announcements", "public"],
    queryFn: ({ signal }) => listPublicAnnouncements({}, signal),
    staleTime: 60_000,
  });
  const items = query.data ?? [];
  if (items.length === 0) return null;
  return (
    <section aria-labelledby="announcements-heading" className="grid gap-3">
      <h2 id="announcements-heading" className="text-lg font-semibold">
        {t("title")}
      </h2>
      <ul className="grid gap-3 md:grid-cols-2">
        {items.map((item) => (
          <AnnouncementCard key={item.id} item={item} />
        ))}
      </ul>
    </section>
  );
}

function AnnouncementCard({ item }: { item: PublicAnnouncement }) {
  const t = useTranslations("track.announcements");
  const tKind = useTranslations("announcementKind");
  const format = useFormatter();
  const localized = useLocalized();
  const Icon = ICONS[item.kind];
  const until = format.dateTime(new Date(item.ends_at), {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  });
  return (
    <li className="flex gap-3 rounded-xl border border-border bg-card p-4 shadow-card">
      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-warning-soft text-warning-soft-foreground">
        <Icon aria-hidden="true" className="size-4" />
      </span>
      <div className="grid min-w-0 gap-1">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {tKind(item.kind)}
          {" · "}
          {item.ward?.name ?? t("wholeCity")}
          {item.category ? ` · ${localized(item.category.name_i18n)}` : null}
        </p>
        <h3 className="font-semibold">{localized(item.title_i18n)}</h3>
        <p className="whitespace-pre-line text-sm text-muted-foreground">
          {localized(item.body_i18n)}
        </p>
        <p className="text-xs text-muted-foreground">{t("until", { until })}</p>
      </div>
    </li>
  );
}
