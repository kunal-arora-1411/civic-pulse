"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useCallback } from "react";
import {
  type AppNotification,
  getUnreadNotificationCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/lib/api";
import { useSession } from "@/lib/auth/use-session";

export const NOTIFICATIONS_KEY = ["notifications"] as const;
const UNREAD_KEY = [...NOTIFICATIONS_KEY, "unread-count"] as const;
/** How often the header badge asks for the unread count. */
export const POLL_MS = 30_000;

/**
 * The unread count for the bell. Polls while the tab is visible (React
 * Query pauses intervals in background tabs) and treats failures as 0:
 * a badge isn't worth an error state.
 */
export function useUnreadCount(): number {
  const { status } = useSession();
  const enabled = status === "authenticated";
  const query = useQuery({
    queryKey: UNREAD_KEY,
    queryFn: ({ signal }) => getUnreadNotificationCount(signal),
    enabled,
    refetchInterval: POLL_MS,
  });
  return enabled ? (query.data ?? 0) : 0;
}

export function useNotificationList(
  params: { unread?: boolean; limit?: number; offset?: number },
  options: { enabled?: boolean } = {},
) {
  const { status } = useSession();
  return useQuery({
    queryKey: [...NOTIFICATIONS_KEY, "list", params],
    queryFn: ({ signal }) => listNotifications(params, signal),
    enabled: status === "authenticated" && (options.enabled ?? true),
    refetchInterval: POLL_MS,
  });
}

export function useMarkRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => markNotificationRead(id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY }),
  });
}

export function useMarkAllRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => markAllNotificationsRead(),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY }),
  });
}

type Loose = ((key: string, values?: Record<string, string>) => string) & {
  has: (key: string) => boolean;
};

/** Title and body of a notification in the reader's language. */
export function useNotificationText() {
  const t = useTranslations("notifications.messages");
  const status = useTranslations("issueStatus");
  return useCallback(
    (item: AppNotification) => {
      const params: Record<string, string> = {};
      for (const [key, value] of Object.entries(item.params)) {
        params[key] = value == null ? "" : String(value);
      }
      // Keys come from the API, so they are checked at runtime rather
      // than against the typed message catalogue.
      const message = t as unknown as Loose;
      const label = status as unknown as Loose;
      if (params.status && label.has(params.status)) {
        params.status = label(params.status);
      }
      const title = message.has(item.title_key)
        ? message(item.title_key, params)
        : t("fallback.title");
      const body = message.has(item.body_key)
        ? message(item.body_key, params)
        : t("fallback.body");
      return { title, body };
    },
    [t, status],
  );
}

/** Splits newest-first notifications into the reader's today and earlier. */
export function groupByDay(
  items: AppNotification[],
  now: Date = new Date(),
): { today: AppNotification[]; earlier: AppNotification[] } {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  const today: AppNotification[] = [];
  const earlier: AppNotification[] = [];
  for (const item of items) {
    (new Date(item.created_at) >= start ? today : earlier).push(item);
  }
  return { today, earlier };
}
