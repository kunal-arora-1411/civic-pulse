import { apiRequest } from "../client";
import {
  type AppNotification,
  type NotificationPage,
  notificationPageSchema,
  notificationSchema,
  readAllSchema,
  unreadCountSchema,
} from "../schemas-notifications";

export function listNotifications(
  params: { unread?: boolean; limit?: number; offset?: number },
  signal?: AbortSignal,
): Promise<NotificationPage> {
  return apiRequest({
    path: "/notifications",
    query: { ...params, unread: params.unread ? true : undefined },
    schema: notificationPageSchema,
    signal,
  });
}

export async function getUnreadNotificationCount(
  signal?: AbortSignal,
): Promise<number> {
  const body = await apiRequest({
    path: "/notifications/unread-count",
    schema: unreadCountSchema,
    signal,
  });
  return body.unread;
}

export function markNotificationRead(id: string): Promise<AppNotification> {
  return apiRequest({
    method: "POST",
    path: `/notifications/${encodeURIComponent(id)}/read`,
    schema: notificationSchema,
  });
}

export async function markAllNotificationsRead(): Promise<number> {
  const body = await apiRequest({
    method: "POST",
    path: "/notifications/read-all",
    schema: readAllSchema,
  });
  return body.updated;
}
