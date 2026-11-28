# ADR 0007: A hash chain, and signed checkpoints, over the audit log

**Status:** accepted
**Date:** 27 November 2026
**Tracking:** A6.3 · PRD §12.1

## Context

`audit_events` is already append-only: a trigger raises on `UPDATE`, `DELETE` and
`TRUNCATE`, and the app role holds only `SELECT` and `INSERT`. But that guarantee
is conditional on trusting the role and the trigger. It detects nothing about a
row that was changed *before* the trigger existed, changed by a role that can
disable it, or silently lost in a restore from an older backup.

PRD §12.1 asks for the log to be append-only **and tamper-evident**. Those are
different properties, and the second one is missing. It is also a stated
prerequisite for closing the retention decision in
[ADR 0006](0006-retention-and-anonymization.md), which left "how long audit rows
live" open pending it.

## Decision

1. **One SHA-256 chain per tenant, plus one for platform events.** Every row
   carries `chain_seq`, `prev_hash` and `hash`, where `hash` is the SHA-256 of a
   length-prefixed canonical framing of the row including `prev_hash`. Per
   tenant, because the table is RLS-protected: a chain spanning tenants could not
   be verified by a tenant-scoped reader, and the gaps would leak the existence of
   another tenant's rows.
2. **The framing is defined once, in SQL**, as `audit_framing_v1`, and mirrored
   in Python (`app/domains/audit/chain.py`). It lives in the database because the
   trigger must chain a row even when it was written by raw SQL, so the definition
   has to be available at `INSERT` time.
3. **A `BEFORE INSERT` trigger extends the chain**, so no application path can
   skip it — including a future one that forgets. None of the ~40 call sites that
   write audit events changed.
4. **The head is one mutable row per chain**, `audit_chain_heads`, and it is also
   the lock. The trigger's `UPDATE … RETURNING` on that row serialises appends per
   chain, which is what makes `chain_seq` contiguous under concurrency without an
   advisory lock or a retry loop.
5. **The head is sealed hourly into an HMAC-signed checkpoint**, with a key held
   in the environment and never in the database. This is what makes a *truncated
   tail* detectable: without it, deleting the newest rows leaves a prefix that
   verifies perfectly.
6. **Verification has two modes.** `db` mode asks Postgres to recompute each hash
   in one statement (fast; the nightly job). `independent` mode recomputes in
   Python and never calls the SQL function, so it still finds a break if somebody
   rewrote `audit_hash_v1` to agree with edited rows. Both are exposed as an admin
   API, a Celery task and `scripts/verify_audit_chain.py`.
7. **The chain is fail-closed.** There is no kill switch and no "unchained" mode:
   if a row cannot be chained, the audited write fails. An unchained row is an
   audit hole that no later verification can distinguish from an attack.

## Consequences

- Every audited write takes a short per-tenant row lock and one SHA-256. The
  budget is ≤ 2 ms p95 added, measured with `scripts/bench_audit_append.py`.
- A failure to chain fails the request. The mitigations are that the head row is
  guaranteed by two paths (a trigger on `tenants`, and an `ON CONFLICT` in the
  append), and that every audited path in the test suite exercises the trigger.
- A schema rollback below `0017` destroys the chain. That is an incident
  decision, not a routine `downgrade` — after checkpoints exist, it destroys
  evidence.
- **An attacker with schema-owner rights is detected, not prevented.** They can
  disable the trigger, rewrite rows, rewrite the heads and rewrite the SQL
  function. What they cannot do is produce a valid HMAC without the key, so
  `independent` mode against a signed checkpoint catches them — but only once it
  runs. This is the honest limit, and it is why external anchoring is designed
  for and not built (`AnchorSink`, §9.4 of the plan).
- A Postgres upgrade that changes the `jsonb` text rendering would change the
  framing. The golden fixture (`tests/fixtures/audit_chain_v1.json`) pins it, so
  that shows up as a red test rather than as silently unverifiable chains.
- Checkpoints hold no personal data — a scope, a sequence and a hash — so they
  can outlive an anonymized actor. That answers the open question ADR 0006 left.
- Ordering by wall clock is not the order of the chain. `occurred_at` uses
  `now()` (transaction start) and may be non-monotonic across rows; `chain_seq`
  is authoritative. Sorting the walk by `occurred_at` would break verification.
