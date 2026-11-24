"use client";

import {
  Bell,
  ClipboardList,
  GitCompareArrows,
  Link2,
  type LucideIcon,
  MapPinPlus,
  RefreshCw,
} from "lucide-react";
import { useFormatter, useNow, useTranslations } from "next-intl";
import { useId } from "react";
import { Link } from "@/i18n/navigation";
import type { AppNotification } from "@/lib/api";
import {
  groupByDay,
  useMarkRead,
  useNotificationText,
} from "@/lib/notifications/hooks";
import { cn } from "@/lib/utils";

const ICONS: Record<string, { icon: LucideIcon; tone: string }> = {
  report_new_issue: {
    icon: MapPinPlus,
    tone: "bg-primary-soft text-primary-soft-foreground",
  },
  report_linked: {
    icon: Link2,
    tone: "bg-info-soft text-info-soft-foreground",
  },
  issue_status: {
    icon: RefreshCw,
    tone: "bg-success-soft text-success-soft-foreground",
  },
  review_task: {
    icon: GitCompareArrows,
    tone: "bg-warning-soft text-warning-soft-foreground",
  },
  assignment: {
    icon: ClipboardList,
    tone: "bg-accent-soft text-accent-foreground",
  },
};
const FALLBACK = { icon: Bell, tone: "bg-secondary text-secondary-foreground" };

function NotificationRow({
  item,
  onNavigate,
  compact,
}: {
  item: AppNotification;
  onNavigate?: () => void;
  compact?: boolean;
}) {
  const t = useTranslations("notifications");
  const text = useNotificationText();
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });
  const markRead = useMarkRead();
  const { title, body } = text(item);
  const unread = item.read_at === null;
  const { icon: Icon, tone } = ICONS[item.kind] ?? FALLBACK;
  const created = new Date(item.created_at);

  const content = (
    <>
      <span
        aria-hidden="true"
        className={cn(
          "grid size-9 shrink-0 place-items-center rounded-full [&_svg]:size-4",
          tone,
        )}
      >
        <Icon />
      </span>
      <span className="grid min-w-0 flex-1 gap-0.5">
        <span
          className={cn(
            "text-sm",
            unread ? "font-semibold" : "font-medium text-foreground/90",
          )}
        >
          {unread ? <span className="sr-only">{t("unread")}: </span> : null}
          {title}
        </span>
        <span
          className={cn(
            "text-sm text-muted-foreground",
            compact && "line-clamp-2",
          )}
        >
          {body}
        </span>
        <time
          dateTime={item.created_at}
          title={format.dateTime(created, {
            dateStyle: "medium",
            timeStyle: "short",
          })}
          className="text-xs text-muted-foreground"
        >
          {format.relativeTime(created, now)}
        </time>
      </span>
      {unread ? (
        <span
          aria-hidden="true"
          className="mt-1.5 size-2.5 shrink-0 rounded-full bg-accent ring-2 ring-card"
        />
      ) : null}
    </>
  );

  const rowClass = cn(
    "flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-start transition-colors hover:bg-muted focus-visible:bg-muted",
    unread && "bg-primary-soft/40",
  );
  const onActivate = () => {
    if (unread) markRead.mutate(item.id);
    onNavigate?.();
  };

  return item.link ? (
    <Link href={item.link} className={rowClass} onClick={onActivate}>
      {content}
    </Link>
  ) : (
    <button type="button" className={rowClass} onClick={onActivate}>
      {content}
    </button>
  );
}

function Group({
  label,
  items,
  onNavigate,
  compact,
}: {
  label: string;
  items: AppNotification[];
  onNavigate?: () => void;
  compact?: boolean;
}) {
  const id = useId();
  if (items.length === 0) return null;
  return (
    <section aria-labelledby={id} className="grid gap-0.5">
      <h3
        id={id}
        className="px-3 pt-2 pb-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase"
      >
        {label}
      </h3>
      <ul className="grid gap-0.5">
        {items.map((item) => (
          <li key={item.id}>
            <NotificationRow
              item={item}
              onNavigate={onNavigate}
              compact={compact}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Newest-first notifications, split into Today and Earlier. */
export function NotificationGroups({
  items,
  onNavigate,
  compact,
}: {
  items: AppNotification[];
  onNavigate?: () => void;
  compact?: boolean;
}) {
  const t = useTranslations("notifications");
  const { today, earlier } = groupByDay(items);
  return (
    <div className="grid gap-1">
      <Group
        label={t("today")}
        items={today}
        onNavigate={onNavigate}
        compact={compact}
      />
      <Group
        label={t("earlier")}
        items={earlier}
        onNavigate={onNavigate}
        compact={compact}
      />
    </div>
  );
}

export function NotificationsEmpty({ unreadOnly }: { unreadOnly?: boolean }) {
  const t = useTranslations("notifications");
  return (
    <div className="grid justify-items-center gap-2 px-6 py-10 text-center">
      <span
        aria-hidden="true"
        className="grid size-12 place-items-center rounded-full bg-muted text-muted-foreground"
      >
        <Bell className="size-5" />
      </span>
      <p className="font-semibold">
        {unreadOnly ? t("emptyUnreadTitle") : t("emptyTitle")}
      </p>
      <p className="max-w-64 text-sm text-muted-foreground">{t("emptyBody")}</p>
    </div>
  );
}
