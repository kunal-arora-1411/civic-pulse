import { z } from "zod";

/*
 * In-app notifications (docs/api/notifications-contract.md). Text arrives
 * as message keys plus parameters; the client renders them in the
 * reader's language under `notifications.messages`.
 */

export const NOTIFICATION_KINDS = [
  "report_new_issue",
  "report_linked",
  "issue_status",
  "review_task",
  "assignment",
  "sla_breach",
] as const;
export type NotificationKind = (typeof NOTIFICATION_KINDS)[number];

export const notificationSchema = z.object({
  id: z.string(),
  // An unknown kind from a newer API still renders, with a generic icon.
  kind: z.string(),
  title_key: z.string(),
  body_key: z.string(),
  params: z.record(z.string(), z.unknown()),
  link: z.string().nullable(),
  issue_id: z.string().nullable(),
  read_at: z.string().nullable(),
  created_at: z.string(),
});
export type AppNotification = z.infer<typeof notificationSchema>;

export const notificationPageSchema = z.object({
  items: z.array(notificationSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
  unread: z.number(),
});
export type NotificationPage = z.infer<typeof notificationPageSchema>;

export const unreadCountSchema = z.object({ unread: z.number() });
export const readAllSchema = z.object({ updated: z.number() });

/*
 * Delivery preferences (docs/api/notification-delivery.md): which kinds also
 * go out by email, SMS and Web Push. The in-app inbox always gets them all.
 */
export const DELIVERY_CHANNELS = ["email", "sms", "push"] as const;
export type DeliveryChannel = (typeof DELIVERY_CHANNELS)[number];

export const notificationPreferencesSchema = z.object({
  items: z.array(
    z.object({
      kind: z.enum(NOTIFICATION_KINDS),
      channels: z.array(
        z.object({
          channel: z.enum(DELIVERY_CHANNELS),
          enabled: z.boolean(),
          default: z.boolean(),
        }),
      ),
    }),
  ),
  available: z.object({
    email: z.boolean(),
    sms: z.boolean(),
    push: z.boolean(),
  }),
  push_public_key: z.string().nullable(),
});
export type NotificationPreferences = z.infer<
  typeof notificationPreferencesSchema
>;

export type PreferenceChange = {
  kind: NotificationKind;
  channel: DeliveryChannel;
  enabled: boolean;
};

export const pushSubscriptionSchema = z.object({
  id: z.string(),
  endpoint: z.string(),
  created_at: z.string(),
});
