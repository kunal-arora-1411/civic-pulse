# Phase 0 API contract

This is the interface between `apps/api` and `apps/web` for Phase 0: tenancy, sign-in, the current user and administration. It describes what is implemented; [`apps/api/openapi.json`](../../apps/api/openapi.json) is the precise, generated form. If either side needs to change it, update this file in the same commit. Phase 1 builds on it in [`phase-1-contract.md`](phase-1-contract.md).

Base URL: `http://localhost:8000` in development. All endpoints are under `/api/v1` except the health checks.

## Conventions

### Tenant resolution
- Unauthenticated requests name their tenant with the `X-Tenant: <slug>` header (for example `demo-city`).
- Authenticated requests get the tenant from the access token. If an `X-Tenant` header is also sent and it doesn't match the token's tenant, the API returns `403 tenant_mismatch`. The web app only sends `X-Tenant` when it has no token.
- Platform administrators have no tenant (`tenant_id: null`). `X-Tenant` is ignored with a platform admin's token.
- An id that belongs to another tenant (for example `GET /admin/users/{id}` for another tenant's user) is `404 not_found`, never `403`.

### Authentication
- Access token: a JWT sent as `Authorization: Bearer <token>`, valid for 15 minutes.
- Refresh token: opaque, rotated on every use, valid for 30 days. It's returned in two ways:
  - as an `HttpOnly; SameSite=Strict` cookie named `cp_refresh`, scoped to `Path=/api/v1/auth` (`Secure` in production). Browsers use this.
  - in the JSON body as `refresh_token`, for non-browser clients.
- `POST /auth/refresh` accepts the cookie or a body `refresh_token`. If a refresh token is used twice, its whole session family is revoked. The one exception is a just-rotated token presented again within 10 seconds (two tabs refreshing at once), which gets a new token instead.
- The web app keeps the access token **in memory only**. When a page loads, it calls `/auth/refresh` with `credentials: "include"` to restore the session. Refreshes are single-flight within a tab and serialised across tabs, so the same token is never sent twice.
- CORS allows `http://localhost:3000` and `http://localhost:3100` with credentials by default (`CORS_ORIGINS`, comma-separated).

### Errors
Every error returns:
```json
{ "error": { "code": "machine_readable_code", "message": "Human readable message.", "details": {}, "request_id": "..." } }
```
Common codes: `validation_error` (422), `unauthenticated` (401), `token_expired` (401), `forbidden` (403), `tenant_mismatch` (403), `mfa_required` (403), `not_found` (404), `conflict` (409), `rate_limited` (429), `idempotency_key_reused` (422), `internal_error` (500), `service_unavailable` (503).

`message` is English and meant for logs; clients show their own translated text for each code.

Sign-in codes:

| Situation | Response |
|---|---|
| Wrong OTP or TOTP code | `400 invalid_code`, with `details.attempts_remaining` |
| Challenge or `mfa_token` expired or already used | `400 code_expired`: start again |
| Fifth wrong code for one challenge (the limit) | `429 too_many_attempts`: the challenge is dead, start again. No `Retry-After`; a new code can be requested straight away, subject to the rate limits. |
| Too many OTP requests | `429 rate_limited`, with a `Retry-After` header and the same number of seconds in `details.retry_after` |
| Rate-limit store (Redis) down | `503 service_unavailable`: fails closed |
| Account deactivated | `403 account_disabled` |
| A platform admin's phone, verified with `X-Tenant` and no account in that tenant | `403 platform_account`: sign in without `X-Tenant`. A platform admin's number is never auto-registered as a citizen. |
| Refresh token missing, unknown, revoked, expired or reused | `401 unauthenticated`, and the `cp_refresh` cookie is cleared |

OTP requests are limited per phone (one every 30 seconds, 5 an hour) and per client IP (30 an hour). The settings are `OTP_RESEND_SECONDS`, `OTP_MAX_PER_HOUR` and `OTP_MAX_PER_IP_PER_HOUR`. The development compose stack loosens the hourly limits to 60 and 1000, because every local browser reaches the API from the same Docker gateway address.

### Other headers
- `X-Request-ID`: echoed back, or generated if missing.
- `Idempotency-Key`: 1–255 printable ASCII characters, supported on create operations: `POST /admin/users` in Phase 0, and required on `POST /reports` in Phase 1. Repeating a key with the same body replays the original response with `Idempotent-Replayed: true`. Reusing a key with a different body returns `422 idempotency_key_reused`. Keys are scoped per tenant, user and operation, and kept for 24 hours. A failed request stores nothing, so it can be retried with the same key.

### Lists
List endpoints accept `limit` (1–100, default 20), `offset` (default 0) and, where noted, `sort` (a field name, `-` for descending, for example `-created_at`). Unknown sort fields are `422`. They return:
```json
{ "items": [...], "total": 123, "limit": 20, "offset": 0 }
```

### Phone numbers
E.164 format (`+919876543210`). The API normalises Indian 10-digit numbers by adding `+91`.

## Roles and permissions

Roles: `citizen`, `community_contributor`, `operator`, `supervisor`, `field_worker`, `municipal_admin`, `platform_admin`.

Staff roles are all of these except `citizen` and `community_contributor`. A role assignment can be scoped to a `department_id` and/or a `jurisdiction_id`. No scope means the whole tenant.

The frontend uses `permissions` from `/users/me` to decide what to show. The backend always enforces permissions itself.

## Endpoints

### Health
| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Liveness check: `{ "status": "ok" }` |
| GET | `/ready` | Readiness check (database and Redis): `{ "status": "ok", "checks": { "database": "ok", "redis": "ok" } }`. When a check fails: `503 { "status": "unavailable", "checks": { ... } }` with that check set to `"error"`. It's a probe, so it doesn't use the error envelope. |

### Tenant
| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/tenants/current` | `X-Tenant` or bearer | `{ id, slug, name, default_locale, supported_locales: ["en","hi"] }`. Phase 1 adds `map`. |

### Auth
| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/v1/auth/otp/request` | `{ phone }` (+ `X-Tenant`, which can be left out only for platform admins) | `200 { challenge_id, expires_in, resend_after }`. Rate limited (see above). |
| POST | `/api/v1/auth/otp/verify` | `{ challenge_id, code }` | Either a **token response** or `200 { mfa_required: true, mfa_token }`. Unknown phone numbers in a tenant become new `citizen` accounts. |
| POST | `/api/v1/auth/mfa/verify` | `{ mfa_token, code }` | Token response |
| POST | `/api/v1/auth/refresh` | `{ refresh_token? }` or the cookie | Token response |
| POST | `/api/v1/auth/logout` | — (bearer token) | `204`. Revokes the session and clears the cookie. |
| POST | `/api/v1/auth/sessions/revoke-all` | — (bearer token) | `204` |
| POST | `/api/v1/auth/mfa/setup` | — (bearer token, staff only) | `{ secret, otpauth_uri }` |
| POST | `/api/v1/auth/mfa/enable` | `{ code }` | `204` |

**Token response:**
```json
{ "access_token": "...", "token_type": "bearer", "expires_in": 900, "refresh_token": "...", "user": { /* same as GET /users/me */ } }
```

### Current user
| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/users/me` | See below |
| PATCH | `/api/v1/users/me` | Any of `{ display_name, email, locale, preferences }`. The web app saves `locale` when a signed-in user switches language, and switches to the saved locale on sign-in. |

```json
{
  "id": "uuid", "tenant_id": "uuid|null", "phone": "+91...", "email": null,
  "display_name": "Asha", "locale": "en", "preferences": {},
  "mfa_enabled": false, "is_staff": false,
  "roles": [{ "role": "citizen", "department_id": null, "jurisdiction_id": null }],
  "permissions": ["report:create", "report:read_own"]
}
```

### Administration (municipal admin)
| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/v1/admin/users` | `user:manage` | Filters: `q` (name/phone/email), `role`, `is_active`. `sort`: `created_at` (default `-created_at`), `display_name`, `phone`, `last_login_at`. |
| POST | `/api/v1/admin/users` | `user:manage` | `{ phone, display_name, email?, roles: [{ role, department_id?, jurisdiction_id? }] }` → `201` user. Supports `Idempotency-Key`. |
| GET | `/api/v1/admin/users/{id}` | `user:manage` | |
| PATCH | `/api/v1/admin/users/{id}` | `user:manage` | `{ display_name?, email?, is_active? }`. Deactivating a user ends their sessions immediately. |
| PUT | `/api/v1/admin/users/{id}/roles` | `user:manage` | `{ roles: [...] }` replaces all of the user's roles |
| GET | `/api/v1/admin/departments` | `config:read` | `sort`: `name` (default), `code`, `created_at` |
| POST | `/api/v1/admin/departments` | `config:manage` | `{ name, code }` |
| GET | `/api/v1/admin/jurisdictions` | `config:read` | `{ id, parent_id, kind, name, code, geometry }`. Filters `kind` (`city`, `zone`, `ward`) and `parent_id`. `geometry` is `null` unless `include_geometry=true`, then a GeoJSON `MultiPolygon`. `sort`: `code` (default), `name`. |
| GET | `/api/v1/admin/audit-events` | `audit:read` | Filters: `actor_id`, `action`, `entity_type`, `entity_id`, `from`, `to`. `sort`: `occurred_at` (default `-occurred_at`). |

Admin user responses (list items, and the responses to create, get, `PATCH` and `PUT .../roles`) use the `/users/me` shape plus `is_active`, `created_at` and `last_login_at`. Admins can't deactivate themselves or remove their own `user:manage` (`409 conflict`).

Audit event:
```json
{ "id": 1, "occurred_at": "...", "actor": { "id": "...", "display_name": "..." }, "action": "user.roles_changed", "entity_type": "user", "entity_id": "...", "before": {}, "after": {}, "request_id": "..." }
```

### Platform (platform admin)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/platform/tenants` | Standard list envelope. Items are the tenant shape plus `is_active` and `created_at`. `sort`: `slug` (default), `name`, `created_at`. |
| POST | `/api/v1/platform/tenants` | `{ slug, name }` → `201` with the same shape. A duplicate slug is `409 conflict`. |

## Seed data (development only, synthetic)

Tenant `demo-city` ("Demo City") with a city boundary (`SYN-CITY`), 2 zones and 4 wards beneath it (synthetic, central Bengaluru), a second synthetic area in West Delhi (`DEL-CITY`, one zone, 4 wards, no seeded issues) so the report flow can be tried from there, and 4 departments (Roads, Solid Waste, Storm Water Drains, Street Lighting). Tenant `other-city` exists for isolation tests. Phase 1 adds categories, the workflow and synthetic issues ([Phase 1 contract, section 8](phase-1-contract.md#8-development-seed-additions)).

| Phone | Role | Tenant |
|---|---|---|
| +919000000000 | platform_admin | — |
| +919000000001 | municipal_admin | demo-city |
| +919000000002 | operator | demo-city |
| +919000000003 | supervisor (Roads) | demo-city |
| +919000000004 | field_worker (Roads) | demo-city |
| +919000000005 | citizen | demo-city |
| +919100000001 | municipal_admin | other-city |

In development, the SMS provider writes OTP codes to the API log, and the fixed code `000000` is also accepted when `DEV_FIXED_OTP=true`. Fixed codes are never accepted in production.
