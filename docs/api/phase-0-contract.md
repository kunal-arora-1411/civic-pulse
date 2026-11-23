# Phase 0 API contract

This is the agreed interface between `apps/api` and `apps/web` for Phase 0. The backend implements it, and the frontend builds against it. If either side needs to change it, update this file in the same commit.

Base URL: `http://localhost:8000` in development. All endpoints are under `/api/v1` except the health checks.

## Conventions

### Tenant resolution
- Unauthenticated requests name their tenant with the `X-Tenant: <slug>` header (for example `demo-city`).
- Authenticated requests get the tenant from the access token. If an `X-Tenant` header is also sent and it doesn't match the token's tenant, the API returns `403 tenant_mismatch`.
- Platform administrators have no tenant (`tenant_id: null`).

### Authentication
- Access token: a JWT sent as `Authorization: Bearer <token>`, valid for 15 minutes.
- Refresh token: opaque, rotated on every use, valid for 30 days. It's returned in two ways:
  - as an `HttpOnly; SameSite=Strict` cookie named `cp_refresh`, scoped to `Path=/api/v1/auth` (`Secure` in production). Browsers use this.
  - in the JSON body as `refresh_token`, for non-browser clients.
- `POST /auth/refresh` accepts the cookie or a body `refresh_token`. If a refresh token is used twice, its whole session family is revoked.
- The web app keeps the access token **in memory only**. When the page loads, it calls `/auth/refresh` with `credentials: "include"` to restore the session.
- CORS allows `http://localhost:3000` with credentials in development.

### Errors
Every error returns:
```json
{ "error": { "code": "machine_readable_code", "message": "Human readable message.", "details": {}, "request_id": "..." } }
```
Common codes: `validation_error` (422), `unauthenticated` (401), `token_expired` (401), `forbidden` (403), `tenant_mismatch` (403), `mfa_required` (403), `not_found` (404), `conflict` (409), `rate_limited` (429), `idempotency_key_reused` (422), `internal_error` (500).

Auth codes for the OTP and MFA steps:
- `invalid_code` (400): the OTP or MFA code is wrong. `details.attempts_remaining` is included when known.
- `code_expired` (400): the OTP challenge or MFA token has expired or used up its attempts. The user has to request a new code.

`rate_limited` responses include a `Retry-After` header and the same number of seconds in `details.retry_after`.

### Other headers
- `X-Request-ID`: echoed back, or generated if missing.
- `Idempotency-Key`: supported on create operations (in Phase 0: `POST /admin/users`). Repeating the same key with the same body replays the original response. Reusing a key with a different body returns `422 idempotency_key_reused`.

### Lists
List endpoints accept `limit` (1–100, default 20), `offset` (default 0) and, where noted, `sort` (for example `-created_at`). They return:
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
| GET | `/ready` | Readiness check (database and Redis): `{ "status": "ok", "checks": { "database": "ok", "redis": "ok" } }`, or 503 |

### Tenant
| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/tenants/current` | `X-Tenant` | `{ id, slug, name, default_locale, supported_locales: ["en","hi"] }` |

### Auth
| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/v1/auth/otp/request` | `{ phone }` (+ `X-Tenant`, which can be left out only for platform admins) | `200 { challenge_id, expires_in, resend_after }`. Rate limited per phone. |
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
| PATCH | `/api/v1/users/me` | Any of `{ display_name, email, locale, preferences }` |

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
| GET | `/api/v1/admin/users` | `user:manage` | Filters: `q` (name/phone/email), `role`, `is_active`; `sort` |
| POST | `/api/v1/admin/users` | `user:manage` | `{ phone, display_name, email?, roles: [{ role, department_id?, jurisdiction_id? }] }` → `201` user. Supports `Idempotency-Key`. |
| GET | `/api/v1/admin/users/{id}` | `user:manage` | |
| PATCH | `/api/v1/admin/users/{id}` | `user:manage` | `{ display_name?, email?, is_active? }` |
| PUT | `/api/v1/admin/users/{id}/roles` | `user:manage` | `{ roles: [...] }` replaces all of the user's roles |
| GET | `/api/v1/admin/departments` | `config:read` | |
| POST | `/api/v1/admin/departments` | `config:manage` | `{ name, code }` |
| GET | `/api/v1/admin/jurisdictions` | `config:read` | `?kind=ward`. Returns `{ id, parent_id, kind, name, code }` without geometry. Add `?include_geometry=true` for GeoJSON. |
| GET | `/api/v1/admin/audit-events` | `audit:read` | Filters: `actor_id`, `action`, `entity_type`, `entity_id`, `from`, `to` |

Admin user responses (list items, and the responses to create, get, `PATCH` and `PUT .../roles`) use the `/users/me` shape plus `"is_active": true` and `"created_at": "<ISO 8601>"`.

Audit event:
```json
{ "id": 1, "occurred_at": "...", "actor": { "id": "...", "display_name": "..." }, "action": "user.roles_changed", "entity_type": "user", "entity_id": "...", "before": {}, "after": {}, "request_id": "..." }
```

### Platform (platform admin)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/platform/tenants` | List tenants |
| POST | `/api/v1/platform/tenants` | `{ slug, name }` |

## Seed data (development only, synthetic)

Tenant `demo-city` ("Demo City") with 2 zones, 4 wards and 4 departments (Roads, Solid Waste, Storm Water Drains, Street Lighting). Tenant `other-city` exists for isolation tests.

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

## Implementation notes (backend)

Details the backend settled while implementing this contract. `apps/api/openapi.json` is the precise, generated form of everything above.

### Auth error codes
| Situation | Response |
|---|---|
| Wrong OTP or TOTP code | `400 invalid_code`, `details.attempts_remaining` |
| Challenge or `mfa_token` expired or already used | `400 code_expired` (start again) |
| Attempt limit for this challenge used up (5) | `429 too_many_attempts` (start again; no `Retry-After`) |
| Too many OTP requests (per phone: 30 s cooldown, 5/hour; per IP: 30/hour) | `429 rate_limited`, `Retry-After` header = `details.retry_after` (seconds) |
| Rate-limit store (Redis) down | `503 service_unavailable` (fails closed) |
| Account deactivated | `403 account_disabled` |
| Phone belongs to a platform admin, OTP verified with `X-Tenant` and no account in that tenant | `403 platform_account`. Sign in without `X-Tenant`. A platform admin's number is never auto-registered as a citizen. |
| Refresh token missing, unknown, revoked, expired or reused | `401 unauthenticated` (the `cp_refresh` cookie is cleared) |

### Behaviour
- **Refresh reuse grace:** presenting a just-rotated refresh token again within 10 seconds (two tabs refreshing at once) returns a new token instead of revoking the session. Outside that window it counts as reuse, and the whole session family is revoked.
- **`X-Tenant` with a platform admin's token** is ignored, since platform tokens have no tenant. For tenant users a mismatch is still `403 tenant_mismatch`.
- **Cross-tenant IDs** (for example `GET /admin/users/{id}` for another tenant's user) return `404 not_found`, never `403`.
- **`Idempotency-Key`** must be 1–255 printable ASCII characters. Replayed responses carry `Idempotent-Replayed: true`. Keys are scoped per tenant, admin and operation, and kept for 24 hours. A failed request stores nothing, so it can be retried with the same key.
- **`GET /ready`** returns `503 {"status": "unavailable", "checks": {...}}` with the failing check set to `"error"`. It's a probe, so it doesn't use the error envelope.
- **Jurisdictions:** `geometry` is `null` unless `include_geometry=true`, in which case it's a GeoJSON `MultiPolygon`. Also filterable by `parent_id`.
- **Admin users** have the `/users/me` shape plus `is_active`, `created_at` and `last_login_at`. Admins can't deactivate themselves or remove their own `user:manage` (`409 conflict`). Deactivating a user ends their sessions immediately.
- **Platform tenants:** `GET /platform/tenants` uses the standard list envelope. Items add `is_active` and `created_at` to the tenant shape. `POST` returns `201` with the same shape, and a duplicate slug is `409 conflict`.
- **Sort fields:** users `created_at` (default `-created_at`), `display_name`, `phone`, `last_login_at`; departments `name` (default), `code`, `created_at`; jurisdictions `code` (default), `name`; audit events `occurred_at` (default `-occurred_at`); tenants `slug` (default), `name`, `created_at`. Unknown fields return `422`.
- **CORS** allows `http://localhost:3000` and `http://localhost:3100` by default (`CORS_ORIGINS`, comma-separated).
