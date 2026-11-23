# ADR 0003: Phone OTP, rotating refresh tokens and staff TOTP

- Status: accepted
- Date: 2026-11-24

## Context

Citizens sign in with a phone number (PRD FR-001), and there are no passwords to manage. Staff have broader access and must use MFA in production (PRD §12.1). Revocation has to be immediate (FR-004), and the web app shouldn't keep long-lived secrets where JavaScript can read them.

## Decision

**Phone OTP**
- Codes are 6 digits, valid for 5 minutes, with 5 attempts per challenge. Only `HMAC-SHA256(secret, challenge_id:code)` is stored. Binding the challenge ID means a leaked hash is useless for any other challenge.
- Requests are rate limited in Redis: per phone across tenants (30-second cooldown, 5 per hour) and per client IP. The limiter **fails closed** (503), because an unmetered SMS endpoint means both an open bill and an open brute-force window.
- A failed attempt is **committed before the error is returned**. Otherwise the request transaction would roll the attempt counter back and the limit would mean nothing.
- An unknown number in a tenant becomes a `citizen`. A platform admin's number is never auto-registered (`403 platform_account`). Requests without a tenant only ever text real platform admins, but the response looks the same either way.
- `DEV_FIXED_OTP` (`000000`) is honoured only when `ENV != production`.
- SMS goes through a `SmsProvider` interface. Development uses a console provider that logs the code.

**Tokens and sessions**
- The access token is a 15-minute HS256 JWT carrying user, tenant and session IDs. **Every request loads the session row and the user's roles**, so logout, revoke-all, deactivation and role changes take effect at once. That costs one small indexed query per request, which is a deliberate trade.
- The refresh token is opaque (256-bit) and stored as a SHA-256 hash. It's rotated on every use and sent both as an `HttpOnly; SameSite=Strict; Path=/api/v1/auth` cookie and in the body for non-browser clients. Each rotation adds a row to the same **family**; logout revokes the family.
- **Reuse detection:** presenting an already-rotated token revokes the whole family and is audited. `SELECT ... FOR UPDATE` serialises concurrent refreshes of one token, so exactly one rotation wins.
- **Grace window (10 s):** two browser tabs refreshing with the same cookie at the same moment would otherwise log the user out everywhere. Inside the window, a repeat presentation gets a sibling token instead of a revocation. The cost is that a thief who replays within 10 seconds of a legitimate rotation isn't caught. `REFRESH_REUSE_GRACE_SECONDS=0` turns the window off.

**Staff MFA (TOTP)**
- `/mfa/setup` and `/mfa/enable` are for staff only. The secret is Fernet-encrypted at rest (`TOTP_ENCRYPTION_KEY`). The last accepted time step is stored, so a code can't be replayed inside its drift window.
- When MFA is enabled, the OTP step returns a 5-minute `mfa_token` instead of tokens. It has its own JWT audience and points at the OTP challenge row, which makes it single-use with its own attempt counter.
- `REQUIRE_STAFF_MFA` (default: on in production only) makes `require()` deny staff permissions with `403 mfa_required` until the session has passed TOTP. Enabling MFA marks the current session verified, and the flag carries across rotation.

## Consequences

- No passwords, so there's no password storage. Argon2 from the plan isn't needed unless a password flow is added.
- The per-request session check adds a database round trip but removes the usual "revoked token still works for 15 minutes" gap.
- HS256 means the API is the only verifier. If another service ever needs to verify tokens, switch to an asymmetric key (EdDSA) and publish a JWKS.
- SMS delivery currently happens inside the request. Moving it to a Celery task through an outbox (Phase 4, notifications) will make it retryable and keep slow providers out of the login path.
