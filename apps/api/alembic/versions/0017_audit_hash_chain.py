"""Audit hash chain: sequence, linkage and signed checkpoints (A6.3).

`audit_events` was already append-only (a trigger rejects UPDATE, DELETE and
TRUNCATE, and the app role holds only SELECT and INSERT), but nothing detected a
row that was changed before that trigger existed, a row changed by a role that
can disable the trigger, or a tail lost when an older backup was restored.

Every row now carries `chain_seq`, `prev_hash` and `hash`, where

    hash = SHA-256(canonical framing of the row ‖ prev_hash)

There is one chain per tenant and one for platform events (`tenant_id` NULL). A
tenant must be able to verify its own chain under row-level security, so a
single chain spanning tenants is not an option: it would contain links the
policy hides.

The chain is extended by a BEFORE INSERT trigger, so no code path -- including
raw SQL -- can write an unchained row. The trigger's UPDATE of the single row
per chain in `audit_chain_heads` is also the lock that serialises appends for
that chain, which is what keeps `chain_seq` contiguous without an advisory lock
or a retry loop.

`audit_framing_v1` is the single definition of what is hashed. It lives in the
database because the trigger needs it at INSERT time; `app/domains/audit/
chain.py` mirrors it byte for byte, and a golden fixture (tests/fixtures/
audit_chain_v1.json) keeps the two honest.

The head is sealed hourly into `audit_checkpoints`, signed with an HMAC key held
outside the database, so a truncated tail is detectable too. Checkpoints are
append-only like the audit log itself.

The chain columns are nullable here and made NOT NULL by 0018, after the
backfill.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-27
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    " OR current_setting('app.bypass_rls', true) = 'on'"
)
# The `prev_hash` of the first event in a chain.
GENESIS = "decode(repeat('00', 32), 'hex')"

FRAME_FIELD = """
CREATE FUNCTION audit_frame_field(p_value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $fn$
    SELECT octet_length(p_value)::text || ':' || p_value
$fn$
"""

# Every optional field is length-prefixed so that no value can be shifted across
# a field boundary (action='a|b' must not frame like action='a', ip='b'), and
# NULL is its own token rather than an empty string. `occurred_at` is framed as
# whole microseconds because ISO text depends on the TimeZone and DateStyle
# settings, while the integer does not.
FRAMING = """
CREATE FUNCTION audit_framing_v1(
    p_prev        bytea,
    p_tenant      uuid,
    p_seq         bigint,
    p_occurred    timestamptz,
    p_actor       uuid,
    p_action      text,
    p_entity_type text,
    p_entity_id   text,
    p_before      jsonb,
    p_after       jsonb,
    p_request_id  text,
    p_ip          text,
    p_user_agent  text
) RETURNS text
LANGUAGE sql STABLE AS $fn$
    SELECT 'civicpulse.audit.v1'
        || '|prev:'          || encode(p_prev, 'hex')
        || '|tenant:'        || coalesce(p_tenant::text, '~')
        || '|seq:'           || p_seq::text
        || '|occurred_at_us:'|| ((extract(epoch FROM p_occurred) * 1000000)::bigint)::text
        || '|actor:'         || coalesce(p_actor::text, '~')
        || '|action:'        || coalesce(audit_frame_field(p_action), '~')
        || '|entity_type:'   || coalesce(audit_frame_field(p_entity_type), '~')
        || '|entity_id:'     || coalesce(audit_frame_field(p_entity_id), '~')
        || '|before:'        || coalesce(audit_frame_field(p_before::text), '~')
        || '|after:'         || coalesce(audit_frame_field(p_after::text), '~')
        || '|request_id:'    || coalesce(audit_frame_field(p_request_id), '~')
        || '|ip:'            || coalesce(audit_frame_field(p_ip), '~')
        || '|user_agent:'    || coalesce(audit_frame_field(p_user_agent), '~')
$fn$
"""

HASH = """
CREATE FUNCTION audit_hash_v1(
    p_prev        bytea,
    p_tenant      uuid,
    p_seq         bigint,
    p_occurred    timestamptz,
    p_actor       uuid,
    p_action      text,
    p_entity_type text,
    p_entity_id   text,
    p_before      jsonb,
    p_after       jsonb,
    p_request_id  text,
    p_ip          text,
    p_user_agent  text
) RETURNS bytea
LANGUAGE sql STABLE AS $fn$
    SELECT digest(convert_to(
        audit_framing_v1($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13), 'UTF8'),
        'sha256')
$fn$
"""

# SECURITY INVOKER (the default) is deliberate. As the definer it would run as
# the table owner, and FORCE ROW LEVEL SECURITY would then hide the platform
# chain's row (tenant_id NULL) from it, because that row matches no tenant
# policy. The app role is therefore granted INSERT and UPDATE on
# audit_chain_heads.
APPEND = """
CREATE FUNCTION audit_chain_append() RETURNS trigger
LANGUAGE plpgsql AS $fn$
DECLARE
    v_seq  bigint;
    v_prev bytea;
BEGIN
    IF NEW.chain_seq IS NOT NULL OR NEW.prev_hash IS NOT NULL OR NEW.hash IS NOT NULL THEN
        RAISE EXCEPTION 'audit_events rows are chained by the database; chain columns must not be supplied'
            USING ERRCODE = 'insufficient_privilege';
    END IF;

    INSERT INTO audit_chain_heads (tenant_id, next_seq, last_hash)
    VALUES (NEW.tenant_id, 1, decode(repeat('00', 32), 'hex'))
    ON CONFLICT ON CONSTRAINT uq_audit_chain_heads_tenant DO NOTHING;

    -- The row lock this UPDATE takes is held until the transaction ends, so
    -- concurrent appends to one chain queue here instead of racing for a
    -- sequence number. A rollback releases the lock and the number together.
    UPDATE audit_chain_heads
       SET next_seq = next_seq + 1
     WHERE tenant_id IS NOT DISTINCT FROM NEW.tenant_id
    RETURNING next_seq - 1, last_hash INTO v_seq, v_prev;

    NEW.chain_seq := v_seq;
    NEW.prev_hash := v_prev;
    NEW.hash := audit_hash_v1(v_prev, NEW.tenant_id, v_seq, NEW.occurred_at, NEW.actor_id,
                              NEW.action, NEW.entity_type, NEW.entity_id,
                              NEW.before, NEW.after, NEW.request_id, NEW.ip, NEW.user_agent);

    UPDATE audit_chain_heads
       SET last_hash = NEW.hash, updated_at = clock_timestamp()
     WHERE tenant_id IS NOT DISTINCT FROM NEW.tenant_id;

    RETURN NEW;
END
$fn$
"""

# A new tenant starts with an empty chain, so its status endpoint reports a head
# before its first audited action rather than "unknown".
SEED_TENANT = """
CREATE FUNCTION audit_chain_seed_tenant() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    INSERT INTO audit_chain_heads (tenant_id, next_seq, last_hash)
    VALUES (NEW.id, 1, decode(repeat('00', 32), 'hex'))
    ON CONFLICT ON CONSTRAINT uq_audit_chain_heads_tenant DO NOTHING;
    RETURN NULL;
END
$fn$
"""

REJECT_CHANGE = """
CREATE FUNCTION audit_checkpoints_reject_change() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$fn$
"""

APP_GRANTS = {
    "audit_chain_heads": "SELECT, INSERT, UPDATE",
    "audit_checkpoints": "SELECT, INSERT",
    "audit_chain_verifications": "SELECT, INSERT, UPDATE, DELETE",
}


def _app_role() -> str:
    role = os.environ.get("APP_DB_USER", "civicpulse_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError(f"Refusing to use unexpected role name {role!r}")
    return role


def _policy_and_grants(table: str, privileges: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
    )
    role = _app_role()
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                EXECUTE format('GRANT {privileges} ON {table} TO %I', '{role}');
            ELSE
                RAISE NOTICE 'role {role} does not exist; skipping grants';
            END IF;
        END
        $$
        """
    )


def upgrade() -> None:
    # --- the chain columns ---------------------------------------------------------------
    op.add_column("audit_events", sa.Column("chain_seq", sa.BigInteger(), nullable=True))
    op.add_column("audit_events", sa.Column("prev_hash", sa.LargeBinary(32), nullable=True))
    op.add_column("audit_events", sa.Column("hash", sa.LargeBinary(32), nullable=True))
    op.create_check_constraint(
        "ck_audit_events_hash_len",
        "audit_events",
        "hash IS NULL OR octet_length(hash) = 32",
    )
    op.create_check_constraint(
        "ck_audit_events_prev_hash_len",
        "audit_events",
        "prev_hash IS NULL OR octet_length(prev_hash) = 32",
    )
    op.create_check_constraint(
        "ck_audit_events_chain_seq",
        "audit_events",
        "chain_seq IS NULL OR chain_seq >= 1",
    )
    # Postgres treats NULLs as distinct in a plain UNIQUE, which would let the
    # platform chain carry duplicate sequence numbers. The platform chain is
    # therefore its own partial index. These indexes are also what the verifier
    # scans in order.
    op.create_index(
        "uq_audit_events_chain_seq",
        "audit_events",
        ["tenant_id", "chain_seq"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )
    op.create_index(
        "uq_audit_events_platform_chain_seq",
        "audit_events",
        ["chain_seq"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
    )

    # --- the head of each chain ----------------------------------------------------------
    op.create_table(
        "audit_chain_heads",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(
                "tenants.id",
                ondelete="RESTRICT",
                name="fk_audit_chain_heads_tenant_id_tenants",
            ),
            nullable=True,
        ),
        sa.Column("next_seq", sa.BigInteger(), nullable=False),
        sa.Column("last_hash", sa.LargeBinary(32), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            name="uq_audit_chain_heads_tenant",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint("next_seq >= 1", name="ck_audit_chain_heads_next_seq"),
        sa.CheckConstraint(
            "octet_length(last_hash) = 32", name="ck_audit_chain_heads_last_hash_len"
        ),
    )
    _policy_and_grants("audit_chain_heads", APP_GRANTS["audit_chain_heads"])

    # The platform chain's head. Written under the bypass so the migration works
    # even where the schema owner is not a superuser (FORCE ROW LEVEL SECURITY
    # applies to a non-superuser owner too).
    op.execute("SELECT set_config('app.bypass_rls', 'on', true)")
    op.execute(
        "INSERT INTO audit_chain_heads (tenant_id, next_seq, last_hash) "
        f"VALUES (NULL, 1, {GENESIS}) "
        "ON CONFLICT ON CONSTRAINT uq_audit_chain_heads_tenant DO NOTHING"
    )
    op.execute("SELECT set_config('app.bypass_rls', 'off', true)")

    # --- signed checkpoints --------------------------------------------------------------
    op.create_table(
        "audit_checkpoints",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(
                "tenants.id",
                ondelete="RESTRICT",
                name="fk_audit_checkpoints_tenant_id_tenants",
            ),
            nullable=True,
        ),
        sa.Column("up_to_seq", sa.BigInteger(), nullable=False),
        sa.Column("head_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("key_id", sa.String(64), nullable=False),
        sa.Column("signature", sa.LargeBinary(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "up_to_seq",
            name="uq_audit_checkpoints_scope_seq",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint("up_to_seq >= 1", name="ck_audit_checkpoints_up_to_seq"),
        sa.CheckConstraint(
            "octet_length(head_hash) = 32", name="ck_audit_checkpoints_head_hash_len"
        ),
        sa.CheckConstraint(
            "octet_length(signature) = 32", name="ck_audit_checkpoints_signature_len"
        ),
    )
    op.create_index(
        "ix_audit_checkpoints_tenant_created",
        "audit_checkpoints",
        ["tenant_id", "created_at"],
    )
    _policy_and_grants("audit_checkpoints", APP_GRANTS["audit_checkpoints"])
    op.execute(REJECT_CHANGE)
    op.execute(
        "CREATE TRIGGER audit_checkpoints_no_update_delete "
        "BEFORE UPDATE OR DELETE ON audit_checkpoints "
        "FOR EACH ROW EXECUTE FUNCTION audit_checkpoints_reject_change()"
    )
    op.execute(
        "CREATE TRIGGER audit_checkpoints_no_truncate "
        "BEFORE TRUNCATE ON audit_checkpoints "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_checkpoints_reject_change()"
    )

    # --- verification runs ---------------------------------------------------------------
    op.create_table(
        "audit_chain_verifications",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(
                "tenants.id",
                ondelete="CASCADE",
                name="fk_audit_chain_verifications_tenant_id_tenants",
            ),
            nullable=False,
        ),
        sa.Column("from_seq", sa.BigInteger(), nullable=False),
        sa.Column("to_seq", sa.BigInteger(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("checked_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("first_bad_seq", sa.BigInteger(), nullable=True),
        sa.Column("failure_reason", sa.String(300), nullable=True),
        # No foreign key: the record of who asked outlives the user it mentions.
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "mode IN ('db', 'independent')", name="ck_audit_chain_verifications_mode"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'passed', 'failed', 'error')",
            name="ck_audit_chain_verifications_status",
        ),
        sa.CheckConstraint(
            "from_seq >= 1 AND to_seq >= from_seq", name="ck_audit_chain_verifications_range"
        ),
    )
    op.create_index(
        "ix_audit_chain_verifications_tenant_started",
        "audit_chain_verifications",
        ["tenant_id", "started_at"],
    )
    # One run in flight per tenant, enforced by the database rather than by a
    # check-then-insert that two requests can both pass.
    op.create_index(
        "uq_audit_chain_verifications_in_flight",
        "audit_chain_verifications",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    _policy_and_grants("audit_chain_verifications", APP_GRANTS["audit_chain_verifications"])

    # --- framing, hashing and the append trigger -----------------------------------------
    op.execute(FRAME_FIELD)
    op.execute(FRAMING)
    op.execute(HASH)
    op.execute(APPEND)
    op.execute(
        "CREATE TRIGGER audit_chain_assign "
        "BEFORE INSERT ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_chain_append()"
    )
    op.execute(SEED_TENANT)
    op.execute(
        "CREATE TRIGGER audit_chain_seed_tenant "
        "AFTER INSERT ON tenants "
        "FOR EACH ROW EXECUTE FUNCTION audit_chain_seed_tenant()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_chain_seed_tenant ON tenants")
    op.execute("DROP FUNCTION IF EXISTS audit_chain_seed_tenant()")
    op.execute("DROP TRIGGER IF EXISTS audit_chain_assign ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_chain_append()")

    op.drop_index("uq_audit_chain_verifications_in_flight", "audit_chain_verifications")
    op.drop_index("ix_audit_chain_verifications_tenant_started", "audit_chain_verifications")
    op.drop_table("audit_chain_verifications")
    op.execute("DROP TRIGGER IF EXISTS audit_checkpoints_no_update_delete ON audit_checkpoints")
    op.execute("DROP TRIGGER IF EXISTS audit_checkpoints_no_truncate ON audit_checkpoints")
    op.execute("DROP FUNCTION IF EXISTS audit_checkpoints_reject_change()")
    op.drop_index("ix_audit_checkpoints_tenant_created", "audit_checkpoints")
    op.drop_table("audit_checkpoints")
    op.drop_table("audit_chain_heads")

    op.execute("DROP FUNCTION IF EXISTS audit_hash_v1")
    op.execute("DROP FUNCTION IF EXISTS audit_framing_v1")
    op.execute("DROP FUNCTION IF EXISTS audit_frame_field")

    op.drop_index("uq_audit_events_platform_chain_seq", "audit_events")
    op.drop_index("uq_audit_events_chain_seq", "audit_events")
    op.drop_constraint("ck_audit_events_chain_seq", "audit_events", type_="check")
    op.drop_constraint("ck_audit_events_prev_hash_len", "audit_events", type_="check")
    op.drop_constraint("ck_audit_events_hash_len", "audit_events", type_="check")
    op.drop_column("audit_events", "hash")
    op.drop_column("audit_events", "prev_hash")
    op.drop_column("audit_events", "chain_seq")
