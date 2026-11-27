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
event. See ADR 0006.

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
room for branches built in parallel and follows `0014`.

## 7. Web app (no API change)

- Installable PWA: `manifest.webmanifest`, `public/sw.js` (offline shell,
  cached pages, Background Sync wake-up), security headers and a CSP.
- Reports sent offline are queued in IndexedDB with their Idempotency-Key
  and `client_created_at`, and sent when the connection returns.
- Voice input for the description through the browser's speech recognition.
- "Delete my personal data" on the citizen profile.

## 8. Tamper-evident audit chain (A6.3)

Every `audit_events` row now carries `chain_seq`, `prev_hash` and `hash`,
assigned by a `BEFORE INSERT` trigger — no caller supplies or sees them, and no
application code changed. One chain per tenant, plus one for platform events
(`tenant_id IS NULL`). `hash` is the SHA-256 of a length-prefixed canonical
framing of the row including `prev_hash`; see
[ADR 0007](../adr/0007-audit-hash-chain.md).

All four endpoints require `audit:read` — held by `municipal_admin` only. No new
permission was introduced.

### `GET /api/v1/admin/audit-chain`

`operation_id: admin_get_audit_chain`. Read-only status of the caller's chain.

```json
{
  "scope": "tenant",
  "events": 1284,
  "head": {"seq": 1284, "hash": "9f2c4b0e…", "occurred_at": "2026-11-27T09:15:02.184312Z"},
  "last_checkpoint": {
    "id": "0b6f…", "up_to_seq": 1200, "head_hash": "…", "key_id": "k1",
    "created_at": "2026-11-27T09:00:00.004120Z", "signature_valid": true
  },
  "unsealed_events": 84,
  "last_verification": {
    "id": "e2a1…", "status": "passed", "mode": "db", "from_seq": 1,
    "to_seq": 1284, "checked_count": 1284, "first_bad_seq": null,
    "failure_reason": null, "started_at": "…", "finished_at": "…"
  },
  "healthy": true
}
```

`healthy` is false when the newest checkpoint's signature does not verify, the
last verification failed, or the head has fallen behind a sealed checkpoint. It
is **not** part of `/ready`: a broken chain is an incident, not an outage.
`events` equals `head.seq` by construction.

### `POST /api/v1/admin/audit-chain/verifications`

`operation_id: admin_start_audit_chain_verification`. **202** with the queued run.

```json
{"from_seq": 1, "to_seq": 1284, "mode": "independent"}
```

All three fields are optional: `from_seq` defaults to `1`, `to_seq` to the head,
`mode` to `"db"`. `mode` is `"db"` (Postgres recomputes, fast) or
`"independent"` (Python recomputes and never trusts the SQL function).

| Status | When |
|---|---|
| `422 validation_failed` | `from_seq < 1`, `to_seq < from_seq`, `to_seq` past the head, an unknown `mode`, or a range larger than `AUDIT_VERIFY_MAX_EVENTS` |
| `409 conflict` | A `pending` or `running` run already exists for this tenant — one in flight per tenant, enforced by a partial unique index rather than a check-then-insert |
| `503 service_unavailable` | The broker is unreachable; the `pending` row is deleted so the next attempt is not blocked |

Starting a run is itself audited (`audit.chain.verification_requested`, chained
like any other event).

### `GET /api/v1/admin/audit-chain/verifications`

`operation_id: admin_list_audit_chain_verifications`. A `Page` of runs, newest
`started_at` first, with an optional `status` filter.

### `GET /api/v1/admin/audit-chain/verifications/{id}`

`operation_id: admin_get_audit_chain_verification`. **404** when the id is unknown
*or belongs to another tenant* — RLS makes the row invisible, and a 404 is the
right answer to both. No error leaks that a run exists.

### `GET /api/v1/admin/audit-chain/checkpoints`

`operation_id: admin_list_audit_checkpoints`. A `Page` of signed seals, newest
`up_to_seq` first, default limit 50. Each item carries `signature_valid`,
computed per row.

### Not exposed over HTTP

- The **platform chain** (`tenant_id IS NULL`): verifying it needs the RLS
  bypass, which no tenant-scoped router may hold. CLI only
  (`scripts/verify_audit_chain.py --platform`).
- **External anchoring** (S3 Object Lock, RFC 3161): designed, not built.

## 9. Schema (A6.3)

Migrations `0017` (columns, framing functions, append trigger, three tables, RLS,
grants) and `0018` (backfill, head seeding, self-check, `NOT NULL`). Both are
reversible. `0018`'s downgrade removes only the `NOT NULL`s: the chain is evidence
once written. Downgrading below `0017` drops the chain entirely.
