# Phase 6 contract: hardening

API changes made for the hardening phase (P6). Everything else is
unchanged; the OpenAPI document (`apps/api/openapi.json`) is the reference.

## 1. Per-address limits on unauthenticated endpoints (P6-07)

| Endpoint | Setting (default) | When Redis is down |
|---|---|---|
| `POST /auth/otp/request` | `OTP_MAX_PER_IP_PER_HOUR` (30), unchanged | 503 |
| `POST /auth/otp/verify` | `OTP_VERIFY_MAX_PER_IP_PER_HOUR` (120) | 503 |
| `POST /auth/mfa/verify` | `MFA_VERIFY_MAX_PER_IP_PER_HOUR` (60) | 503 |
| `POST /auth/refresh` | `REFRESH_MAX_PER_IP_PER_HOUR` (600) | 503 |
| `GET /tenants/current` | `TENANT_LOOKUP_MAX_PER_IP_PER_MINUTE` (300) | not limited |
| `GET /public/{tenant}/…` | `PUBLIC_MAX_PER_IP_PER_MINUTE` (300), was a constant | not limited |

Over the limit: `429 rate_limited` with `Retry-After` and
`details.retry_after`, the same as the existing limits. The limits are
generous because carrier-grade NAT puts many phones behind one address.
Compose raises them for development, where every browser shares Docker's
gateway address.

## 2. Malware scanning of uploads (P6-07)

`POST /media/uploads/{id}/complete` scans the file with ClamAV after the
image checks when `CLAMAV_HOST` is set (clamd INSTREAM over TCP,
`CLAMAV_PORT` 3310, `CLAMAV_TIMEOUT_SECONDS` 30).

- A signature found: `422 upload_verification_failed` with
  `details.reason = "malware_detected"`; the object is deleted and the
  upload is `failed`, as for other verification failures.
- Scanner configured but unreachable or erroring: `503 service_unavailable`.
  The upload stays `pending`, so completing it again later works. Uploads
  are never accepted unscanned while scanning is on.

Compose has an opt-in `clamav` service (`--profile scan`).

## 3. Account anonymization (P6-12)

`POST /users/me/anonymize` → `204`, clears the refresh cookie. Citizens
only: staff get `403` (an administrator deactivates staff accounts).

Wipes the phone (replaced by a random number under the reserved `+999`
code), email, display name, preferences and MFA secret, sets
`is_active = false` and `anonymized_at`, ends every session (and clears their
IP and user agent), deletes pending OTP challenges for the old number and
clears the private EXIF copy of the user's photos. Reports, issues, support
and audit rows stay. Signing in again with the same number creates a new,
empty account. Audited as `user.anonymized`, with no personal data in the
event. See ADR 0005.

## 4. Original-photo retention (P6-12)

`MEDIA_ORIGINAL_RETENTION_DAYS` (default 0 = keep forever, until the
retention periods are decided). When set, the hourly housekeeping job
deletes the original object of `ready` photos processed longer ago than
that, sets `media_assets.original_purged_at` and clears their EXIF. Only
photos whose public variants exist (and that passed the face check when
blurring is on) are purged. Afterwards staff responses carry
`original_url: null` for them; the thumb and display variants are unchanged.

## 5. Observability (P6-10)

Opt-in through the environment: `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE`,
`OTEL_EXPORTER_OTLP_ENDPOINT`, `RELEASE`. No API shape changes. Sentry
never receives request bodies, cookies, auth headers, user data or local
variables.

## 6. Schema

Migration `0015` adds `users.anonymized_at`, `media_assets.original_purged_at`
and a partial index for the retention job. It is numbered 0015 to leave
room for branches built in parallel and follows `0011` until they merge.

## 7. Web app (no API change)

- Installable PWA: `manifest.webmanifest`, `public/sw.js` (offline shell,
  cached pages, Background Sync wake-up), security headers and a CSP.
- Reports sent offline are queued in IndexedDB with their Idempotency-Key
  and `client_created_at`, and sent when the connection returns.
- Voice input for the description through the browser's speech recognition.
- "Delete my personal data" on the citizen profile.
