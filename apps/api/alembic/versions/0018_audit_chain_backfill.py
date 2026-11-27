"""Backfill the audit hash chain and make the chain columns NOT NULL (A6.3).

`audit_events` rows written before 0017 have no `chain_seq`, `prev_hash` or
`hash`. Chaining them is sequential -- the hash of a row contains the hash of the
row before it -- so it cannot be done with `lag()`; a recursive walk assigns the
sequence and the previous hash, and each row's hash is computed from those.

This migration has to disable two triggers:

* `audit_events_no_update_delete`, because it rejects exactly the UPDATE the
  backfill performs. Disabling it needs table-owner rights, which is why the
  backfill is a migration and not something a running service can do.
* `audit_chain_assign`, because it refuses rows that supply chain columns.

Both are re-enabled before the migration finishes. Migrations run in one
transaction, so a failure rolls the disable/backfill/enable back together and
leaves no window where a running API could write an unchained row.

It also creates a head row for every chain that has rows. 0017 only seeds the
platform head and a trigger seeds new tenants, so every tenant that existed
before this feature would otherwise have no head: its chain would read as empty
and its next audited write would try chain_seq 1 against rows that already
occupy it.

The last statements re-verify every chain in SQL and refuse to commit a chain
that does not verify. A migration must not be able to corrupt the audit trail.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-27
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GENESIS = "decode(repeat('00', 32), 'hex')"

# Rows already chained (none on a first run) tell us where each chain resumes.
BACKFILL = f"""
WITH RECURSIVE
chained AS (
    SELECT tenant_id, max(chain_seq) AS last_seq
      FROM audit_events
     WHERE hash IS NOT NULL
     GROUP BY tenant_id
),
pending AS (
    SELECT e.id, e.tenant_id,
           row_number() OVER (PARTITION BY e.tenant_id ORDER BY e.id)
             + coalesce(c.last_seq, 0) AS seq
      FROM audit_events e
      LEFT JOIN chained c ON c.tenant_id IS NOT DISTINCT FROM e.tenant_id
     WHERE e.hash IS NULL
),
walk AS (
    SELECT p.id, p.tenant_id, p.seq, coalesce(h.last_hash, {GENESIS}) AS prev_hash
      FROM pending p
      LEFT JOIN audit_chain_heads h ON h.tenant_id IS NOT DISTINCT FROM p.tenant_id
     WHERE p.seq = (SELECT min(p2.seq) FROM pending p2
                     WHERE p2.tenant_id IS NOT DISTINCT FROM p.tenant_id)
    UNION ALL
    SELECT n.id, n.tenant_id, n.seq,
           audit_hash_v1(w.prev_hash, prior.tenant_id, w.seq, prior.occurred_at,
                         prior.actor_id, prior.action, prior.entity_type, prior.entity_id,
                         prior.before, prior.after, prior.request_id, prior.ip,
                         prior.user_agent)
      FROM walk w
      JOIN audit_events prior ON prior.id = w.id
      JOIN pending n ON n.tenant_id IS NOT DISTINCT FROM w.tenant_id AND n.seq = w.seq + 1
)
UPDATE audit_events t
   SET chain_seq = w.seq,
       prev_hash = w.prev_hash,
       hash = audit_hash_v1(w.prev_hash, t.tenant_id, w.seq, t.occurred_at, t.actor_id,
                            t.action, t.entity_type, t.entity_id, t.before, t.after,
                            t.request_id, t.ip, t.user_agent)
  FROM walk w
 WHERE t.id = w.id
"""

ADVANCE_HEADS = """
INSERT INTO audit_chain_heads (tenant_id, next_seq, last_hash)
SELECT tail.tenant_id, tail.max_seq + 1, tail.head_hash
  FROM (SELECT tenant_id,
               max(chain_seq) AS max_seq,
               (array_agg(hash ORDER BY chain_seq DESC))[1] AS head_hash
          FROM audit_events
         GROUP BY tenant_id) tail
ON CONFLICT ON CONSTRAINT uq_audit_chain_heads_tenant DO UPDATE
   SET next_seq = EXCLUDED.next_seq,
       last_hash = EXCLUDED.last_hash,
       updated_at = clock_timestamp()
"""

# The same three questions the verifier asks, asked once in the database before
# the migration is allowed to commit: is every row linked to the one before it,
# does every stored hash recompute, and is every chain contiguous from 1?
LINK_AND_HASH_VIOLATIONS = """
SELECT count(*)
  FROM (SELECT e.tenant_id,
               lag(e.hash) OVER (PARTITION BY e.tenant_id ORDER BY e.chain_seq) AS prior_hash,
               e.prev_hash,
               e.hash,
               audit_hash_v1(e.prev_hash, e.tenant_id, e.chain_seq, e.occurred_at, e.actor_id,
                             e.action, e.entity_type, e.entity_id, e.before, e.after,
                             e.request_id, e.ip, e.user_agent) AS expected_hash
          FROM audit_events e) checked
 WHERE (prior_hash IS NOT NULL AND prev_hash <> prior_hash)
    OR hash <> expected_hash
"""

CONTIGUITY_VIOLATIONS = """
SELECT count(*)
  FROM (SELECT tenant_id
          FROM audit_events
         GROUP BY tenant_id
        HAVING min(chain_seq) <> 1 OR max(chain_seq) <> count(*)) broken
"""

# Asked of every chain that has rows, not of every head that exists. A tenant
# created before 0017 has no head row at all (only the platform head and new
# tenants get one), and a check that walked the heads table would call that
# healthy while the chain read as empty and the next append collided on
# chain_seq 1.
HEAD_VIOLATIONS = """
SELECT count(*)
  FROM (SELECT tenant_id,
               max(chain_seq) AS max_seq,
               (array_agg(hash ORDER BY chain_seq DESC))[1] AS head_hash
          FROM audit_events
         GROUP BY tenant_id) tail
  LEFT JOIN audit_chain_heads h ON h.tenant_id IS NOT DISTINCT FROM tail.tenant_id
 WHERE h.id IS NULL
    OR h.next_seq <> tail.max_seq + 1
    OR h.last_hash <> tail.head_hash
"""

# `audit_events` and `audit_chain_heads` both carry FORCE ROW LEVEL SECURITY, and
# a migration owner need not be a superuser -- 0017 does its own head write under
# the bypass for the same reason.
BYPASS_ON = "SELECT set_config('app.bypass_rls', 'on', true)"
BYPASS_OFF = "SELECT set_config('app.bypass_rls', 'off', true)"

# Chaining is sequential, so the backfill holds row locks for its duration. It is
# a migration-time cost on a pilot-sized table, but on a very large one it would
# be an outage. Refuse rather than pretend. Overridable so an operator can raise
# it deliberately for a known-large restore, and so the guard can be tested
# without writing two million rows.
MAX_ROWS = int(os.environ.get("AUDIT_BACKFILL_MAX_ROWS", "2000000"))


def _scalar(statement: str) -> int:
    value = op.get_bind().execute(sa.text(statement)).scalar()
    return int(value or 0)


def upgrade() -> None:
    total = _scalar("SELECT count(*) FROM audit_events")
    if total > MAX_ROWS:
        raise RuntimeError(
            f"audit_events holds {total} rows; the hash-chain backfill is sequential and "
            f"refuses more than {MAX_ROWS} in one migration. Chain them in batches first "
            "(see docs/specs/audit-hash-chain-implementation-plan.md §8.3)."
        )

    op.execute("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update_delete")
    op.execute("ALTER TABLE audit_events DISABLE TRIGGER audit_chain_assign")
    op.execute(BYPASS_ON)

    op.execute(BACKFILL)
    op.execute(ADVANCE_HEADS)

    for name, statement in (
        ("link or hash", LINK_AND_HASH_VIOLATIONS),
        ("contiguity", CONTIGUITY_VIOLATIONS),
        ("chain head", HEAD_VIOLATIONS),
    ):
        violations = _scalar(statement)
        if violations:
            raise RuntimeError(f"the backfilled audit chain has {violations} {name} violations")

    op.execute("ALTER TABLE audit_events ALTER COLUMN chain_seq SET NOT NULL")
    op.execute("ALTER TABLE audit_events ALTER COLUMN prev_hash SET NOT NULL")
    op.execute("ALTER TABLE audit_events ALTER COLUMN hash SET NOT NULL")

    op.execute(BYPASS_OFF)
    op.execute("ALTER TABLE audit_events ENABLE TRIGGER audit_chain_assign")
    op.execute("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update_delete")


def downgrade() -> None:
    # The columns stay: they are evidence once written, and a rollback of 0017
    # drops them anyway. Only the constraint the previous revision did not have
    # is removed, so `0017 -> 0018` can be replayed.
    op.execute("ALTER TABLE audit_events ALTER COLUMN hash DROP NOT NULL")
    op.execute("ALTER TABLE audit_events ALTER COLUMN prev_hash DROP NOT NULL")
    op.execute("ALTER TABLE audit_events ALTER COLUMN chain_seq DROP NOT NULL")
