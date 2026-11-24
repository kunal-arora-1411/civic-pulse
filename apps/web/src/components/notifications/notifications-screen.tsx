"use client";

import { CheckCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Pagination } from "@/components/admin/pagination";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useMarkAllRead, useNotificationList } from "@/lib/notifications/hooks";
import { cn } from "@/lib/utils";
import { NotificationGroups, NotificationsEmpty } from "./notification-list";

const LIMIT = 20;

/** Every notification, newest first, with an All / Unread switch. */
export function NotificationsScreen() {
  const t = useTranslations("notifications");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const list = useNotificationList({
    unread: unreadOnly,
    limit: LIMIT,
    offset,
  });
  const markAll = useMarkAllRead();
  const unread = list.data?.unread ?? 0;

  const tab = (value: boolean, label: string) => (
    <button
      type="button"
      aria-pressed={unreadOnly === value}
      onClick={() => {
        setUnreadOnly(value);
        setOffset(0);
      }}
      className={cn(
        "rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground",
        unreadOnly === value && "bg-card text-foreground shadow-card",
      )}
    >
      {label}
    </button>
  );

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <fieldset className="inline-flex gap-1 rounded-lg bg-muted p-1">
          <legend className="sr-only">{t("filterLabel")}</legend>
          {tab(false, t("filterAll"))}
          {tab(true, t("filterUnread", { count: unread }))}
        </fieldset>
        <Button
          variant="outline"
          size="sm"
          disabled={unread === 0 || markAll.isPending}
          onClick={() => markAll.mutate()}
        >
          <CheckCheck aria-hidden="true" />
          {t("markAllRead")}
        </Button>
      </div>
      <div className="rounded-xl border border-border bg-card p-2 shadow-card">
        {list.isPending ? (
          <div className="grid gap-2 p-2" aria-busy="true">
            <span className="sr-only">{t("loading")}</span>
            {[0, 1, 2, 3].map((n) => (
              <Skeleton key={n} className="h-16" />
            ))}
          </div>
        ) : list.isError ? (
          <Alert variant="destructive">{t("loadError")}</Alert>
        ) : list.data.items.length === 0 ? (
          <NotificationsEmpty unreadOnly={unreadOnly} />
        ) : (
          <NotificationGroups items={list.data.items} />
        )}
      </div>
      {list.data ? (
        <Pagination
          offset={offset}
          limit={LIMIT}
          total={list.data.total}
          onOffsetChange={setOffset}
          label={t("pagesLabel")}
        />
      ) : null}
    </div>
  );
}
