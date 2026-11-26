# API contract: notification delivery (email, SMS, Web Push)

Base path `/api/v1`, tenant from `X-Tenant`, bearer token, errors in the
usual envelope (phase-0-contract.md). This extends the in-app notifications
in [analytics-notifications.md §2](analytics-notifications.md#2-in-app-notifications)
and covers PRD §15 and P4-03, P4-04 and P4-06.

## 1. How a notification leaves the building

1. A database trigger writes the in-app notification (migration 0008, plus
   the SLA scanner). The inbox always gets every notification.
2. In the same transaction, a second trigger (migration 0012) writes an
   outbox event `notification.created` with payload
   `{notification_id, user_id, kind, issue_id}`. A change that rolls back
   sends nothing.
3. The outbox dispatcher (every 20 s) offers the event to each configured
   channel. Each one checks, in order: the recipient's account is active,
   they keep this kind on for this channel, and they were not sent an
   identical notification (same kind, issue and parameters) on this channel
   in the last `NOTIFICATION_DEDUP_MINUTES` (10). SMS is also capped at
   `NOTIFICATION_SMS_PER_DAY` (10) texts per person per day.
4. Every outcome is one `outbox_deliveries` row per event and channel:
   `delivered` (with the provider's message id where there is one),
   `skipped` (with the reason) or `failed` (with the error).

**Wording is lock-screen safe (PRD §15.2).** Email, SMS and push carry the
same text as the inbox: references and a status, never an address,
description, photo or reporter. They are rendered on the server in the
recipient's language (`users.locale`, English or Hindi) by
`app/domains/notifications/render.py`, which mirrors
`notifications.messages` in the web app's catalogues.

| Channel | Switched on by | Sends |
|---|---|---|
| `email` | `SMTP_HOST` | Every notification kind except `assignment`, which the richer `issue.assigned` email covers. Subject is the title; the body links to the item and to `/profile` to change settings. |
| `sms` | always (`SMS_PROVIDER`, `console` logs in development) | `CivicPulse: <title>. <link>`. Also sign-in codes (§4). |
| `push` | `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` | `{title, body, url, tag}` to every subscribed browser. A push service answering 404/410 has dropped the browser: the subscription is deleted, not retried. |

No real SMS provider is chosen yet. MSG91 and Gupshup are the candidates;
both need DLT-registered templates. Adding one is a class implementing
`send_otp` and `send_text` in `app/domains/auth/sms.py`.

## 2. Retries and dead letters (P4-06)

A `failed` delivery is retried with exponential backoff: 30 s, 1 min,
2 min, 4 min (capped at an hour), stored in `outbox_events.next_attempt_at`.
A retry asks only the channels that have not delivered the event yet. After
5 attempts the event becomes a **dead letter** (`dead_lettered_at`,
`last_error`): it is no longer retried, it is never purged by retention, and
administrators can see it and send it again.

All endpoints need **`config:manage`** (municipal admin). Without it: `403`.
Results are limited to the caller's tenant by RLS. Payloads are never
returned, because they can hold contact details.

| Method and path | Response |
|---|---|
| `GET /admin/outbox/dead-letters?limit&offset` | Page of `{id, event_type, aggregate_type, aggregate_id, attempts, last_error, created_at, dead_lettered_at, deliveries: [{channel, outcome, detail, created_at}]}`, newest dead letter first |
| `POST /admin/outbox/dead-letters/{id}/retry` | The event, back in the queue with `attempts` reset. Audited as `outbox.dead_letter_retried`. Not a dead letter (or another tenant's): `404` |

## 3. Preferences and Web Push subscriptions

Any signed-in user with a tenant. A platform administrator (no tenant) gets
`403`. Only a person's own settings are ever read or written.

### `GET /notifications/preferences`

```json
{
  "items": [
    {"kind": "issue_status", "channels": [
      {"channel": "push", "enabled": true, "default": true},
      {"channel": "email", "enabled": true, "default": true},
      {"channel": "sms", "enabled": false, "default": true}
    ]}
  ],
  "available": {"email": true, "sms": true, "push": false},
  "push_public_key": null
}
```

`items` lists only the kinds the caller can receive: citizen kinds
(`report_new_issue`, `report_linked`, `issue_status`) for `report:create`,
and staff kinds (`review_task`, `assignment`, `sla_breach`) for
`issue:read`. Each kind lists only the channels PRD §15.1 allows for it:

| Kind | Email | SMS | Push |
|---|---|---|---|
| `report_new_issue` | on | on | — |
| `report_linked` | — | on | on |
| `issue_status` | on | on | on |
| `review_task` | off | — | on |
| `assignment` | on | — | on |
| `sla_breach` | on | — | on |

(on/off is the default; — means never sent there.) `available` says whether
a channel can reach the person at all: a relay and an email address; a
mobile number; Web Push configured. `push_public_key` is the VAPID key a
browser subscribes with, or `null` when push is off.

### `PUT /notifications/preferences`

Body `{"items": [{"kind", "channel", "enabled"}]}` (1–50 items). Only the
listed choices change. A kind the caller cannot receive, or a channel the
kind is never sent on: `422`. Returns the same shape as `GET`.

### `POST /notifications/push-subscriptions`

Body: the browser's `PushSubscription.toJSON()`,
`{"endpoint", "keys": {"p256dh", "auth"}}`. `201` with
`{id, endpoint, created_at}`. Subscribing the same endpoint again updates it
and moves it to the caller (a shared device). The endpoint must be `https`
on a known browser push service (`PUSH_ENDPOINT_HOSTS`: FCM, Mozilla, Apple,
Windows), otherwise `422`; this stops the server being aimed at internal
hosts. Push not configured: `503`.

### `DELETE /notifications/push-subscriptions?endpoint=…`

`204`, idempotent; removes only the caller's own subscription.

The web app's service worker is `/sw.js`. It shows the push and opens its
`url` on click. Settings live on `/profile`.

## 4. Sign-in codes

`POST /auth/otp/request` no longer texts the code inside the request. It
writes an `auth.otp` outbox event in the same transaction as the challenge.
The code is Fernet-encrypted in the payload (`TOTP_ENCRYPTION_KEY`), and the
event is delivered by a job straight after the commit, so the response does
not wait on the provider. If the broker is down, the dispatcher's next tick
sends it instead. A code that expired while queued is `skipped`, not sent.
The response and the dev code `000000` are unchanged. A platform
administrator's code has no tenant (`outbox_events.tenant_id` is `NULL`) and
is only reachable through the explicit RLS bypass.
