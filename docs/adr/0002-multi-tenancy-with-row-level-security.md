# ADR 0002: Multi-tenancy with Postgres row-level security

- Status: accepted
- Date: 2026-11-24

## Context

Each municipality is a tenant, and AC-14 requires that one tenant can never read another's data. If every query has to remember `WHERE tenant_id = ...`, the first time one forgets is a cross-tenant leak, and code review is a weak defence against omissions.

## Decision

Share one schema and enforce isolation in the database with **row-level security**:

- Every table with a `tenant_id` gets one policy:
  `tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.bypass_rls', true) = 'on'`,
  for both `USING` and `WITH CHECK`, and the policy is `FORCE`d.
- **The API never connects as a superuser or table owner.** It uses `civicpulse_app` (`NOSUPERUSER NOBYPASSRLS`), created by the database init script. Migrations run as the owner role in a separate one-shot `migrate` service, which is the only place the owner credentials go.
- **One transaction per request.** The tenant is set inside it with `set_config('app.tenant_id', ..., true)`, so the setting is transaction-local and can't leak to the next request on a pooled connection. The desired context lives in `session.info`, and an `after_begin` listener re-applies it to every new transaction the session opens.
- **The tenant comes from the access token** for authenticated requests and from `X-Tenant` for anonymous ones. If a header disagrees with a tenant user's token, the request gets `403 tenant_mismatch`.
- **The bypass is explicit.** It's reachable only through `rls_bypass(session, reason=...)` or `acting_as(session, None, ...)`, and each use is logged with its reason. Legitimate uses: platform-admin identity and self-service (their rows have `tenant_id IS NULL`), lookups by an unguessable capability before the tenant is known (OTP challenge ID, refresh-token hash), platform audit events, the seed script, and system jobs.
- **The database also enforces integrity across tenants**, not just reads. Composite `(tenant_id, id)` foreign keys stop a role from being scoped to another tenant's department or jurisdiction.

## Consequences

- A forgotten tenant filter fails closed. With no tenant set, the policy compares against NULL and nothing is visible. The test suite checks this as the app role, including across a single pooled connection.
- Cross-tenant IDs behave like missing rows, so the API returns 404 rather than 403 and confirms nothing.
- Every transaction pays for one extra `set_config` round trip, which is negligible.
- The `OR bypass` predicate can stop the planner from using `tenant_id` indexes in some plans. That's fine at pilot scale. If it shows up in profiling, split it into two permissive policies or add explicit tenant filters to hot queries.
- Analytics and exports across tenants (platform reporting) will need deliberate, audited bypass paths. That's intentional friction.
