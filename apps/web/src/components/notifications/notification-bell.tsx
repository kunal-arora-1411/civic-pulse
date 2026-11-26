"use client";

import { Bell, CheckCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Link } from "@/i18n/navigation";
import { useSession } from "@/lib/auth/use-session";
import {
  useMarkAllRead,
  useNotificationList,
  useUnreadCount,
} from "@/lib/notifications/hooks";
import { cn } from "@/lib/utils";
import { NotificationGroups, NotificationsEmpty } from "./notification-list";

const PANEL_LIMIT = 8;

/**
 * Header bell: unread badge (polled) and a disclosure panel with the
 * latest notifications. A disclosure rather than an ARIA menu, like the
 * account menu: the rows are links, so Tab order is what people expect.
 * Escape closes it and returns focus to the bell.
 */
export function NotificationBell({
  align = "end",
  className,
}: {
  align?: "start" | "end";
  className?: string;
}) {
  const t = useTranslations("notifications");
  const { status } = useSession();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const headingId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const unread = useUnreadCount();
  const list = useNotificationList({ limit: PANEL_LIMIT }, { enabled: open });
  const markAll = useMarkAllRead();

  useLayoutEffect(() => () => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (status !== "authenticated") return null;

  const items = list.data?.items ?? [];
  const badge = unread > 99 ? "99+" : String(unread);

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
        className="relative grid size-9 place-items-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <Bell aria-hidden="true" className="size-5" />
        <span className="sr-only">
          {unread > 0
            ? t("bellLabelUnread", { count: unread })
            : t("bellLabel")}
        </span>
        {unread > 0 ? (
          <span
            aria-hidden="true"
            className="absolute -top-0.5 -end-0.5 grid h-[1.125rem] min-w-[1.125rem] place-items-center rounded-full bg-accent px-1 text-[0.6875rem] leading-none font-bold text-accent-foreground tabular-nums ring-2 ring-card"
          >
            {badge}
          </span>
        ) : null}
      </button>
      <section
        id={panelId}
        hidden={!open}
        aria-labelledby={headingId}
        className={cn(
          "absolute top-full z-40 mt-2 w-[min(24rem,calc(100vw-2rem))] rounded-xl border border-border bg-card shadow-raised motion-safe:animate-fade",
          align === "end" ? "end-0" : "start-0",
        )}
      >
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <h2 id={headingId} className="font-semibold">
            {t("title")}
          </h2>
          <Button
            variant="ghost"
            size="sm"
            disabled={unread === 0 || markAll.isPending}
            onClick={() => markAll.mutate()}
          >
            <CheckCheck aria-hidden="true" />
            {t("markAllRead")}
          </Button>
        </div>
        <div className="max-h-[min(28rem,70dvh)] overflow-y-auto p-1.5">
          {list.isPending ? (
            <div className="grid gap-2 p-2" aria-busy="true">
              <span className="sr-only">{t("loading")}</span>
              <Skeleton className="h-14" />
              <Skeleton className="h-14" />
              <Skeleton className="h-14" />
            </div>
          ) : list.isError ? (
            <p role="alert" className="p-4 text-sm text-destructive">
              {t("loadError")}
            </p>
          ) : items.length === 0 ? (
            <NotificationsEmpty />
          ) : (
            <NotificationGroups
              items={items}
              compact
              onNavigate={() => setOpen(false)}
            />
          )}
        </div>
        <div className="border-t border-border p-1.5">
          <Link
            href="/notifications"
            onClick={() => setOpen(false)}
            className="block rounded-lg px-3 py-2 text-center text-sm font-semibold text-primary hover:bg-muted"
          >
            {t("viewAll")}
          </Link>
        </div>
      </section>
    </div>
  );
}
