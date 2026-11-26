import { apiRequest } from "../client";
import {
  type AppNotification,
  type NotificationPage,
  type NotificationPreferences,
  notificationPageSchema,
  notificationPreferencesSchema,
  notificationSchema,
  type PreferenceChange,
  pushSubscriptionSchema,
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

export function getNotificationPreferences(
  signal?: AbortSignal,
): Promise<NotificationPreferences> {
  return apiRequest({
    path: "/notifications/preferences",
    schema: notificationPreferencesSchema,
    signal,
  });
}

export function updateNotificationPreferences(
  items: PreferenceChange[],
): Promise<NotificationPreferences> {
  return apiRequest({
    method: "PUT",
    path: "/notifications/preferences",
    body: { items },
    schema: notificationPreferencesSchema,
  });
}

/** Register this browser's `PushSubscription.toJSON()` with the API. */
export async function savePushSubscription(subscription: {
  endpoint: string;
  keys: { p256dh: string; auth: string };
}): Promise<void> {
  await apiRequest({
    method: "POST",
    path: "/notifications/push-subscriptions",
    body: subscription,
    schema: pushSubscriptionSchema,
  });
}

export function deletePushSubscription(endpoint: string): Promise<void> {
  return apiRequest({
    method: "DELETE",
    path: "/notifications/push-subscriptions",
    query: { endpoint },
  });
}
