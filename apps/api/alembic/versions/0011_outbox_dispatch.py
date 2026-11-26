"""Outbox delivery: the dispatcher's retry count and its delivery log.

ADR 0004 left the dispatcher to Phase 4; this is it. `outbox_events.attempts`
counts delivery tries so a poison event stops being retried, and
`outbox_deliveries` records one row per (event, channel) attempt. Rows in the
log are append-only, so the app role gets no UPDATE on it.

Dispatched events are deleted after the retention window by housekeeping;
deliveries cascade with their event.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-25
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    " OR current_setting('app.bypass_rls', true) = 'on'"
)


def _app_role() -> str:
    role = os.environ.get("APP_DB_USER", "civicpulse_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError(f"Refusing to use unexpected role name {role!r}")
    return role


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    # outbox_deliveries references (tenant_id, id) on outbox_events, so the
    # referenced pair has to be unique. Every tenant-scoped table in this
    # schema carries the same key for exactly this reason.
    op.create_unique_constraint(
        "uq_outbox_events_tenant_id_id", "outbox_events", ["tenant_id", "id"]
    )
    op.create_table(
        "outbox_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(
                "tenants.id",
                ondelete="RESTRICT",
                name="fk_outbox_deliveries_tenant_id_tenants",
            ),
            nullable=False,
        ),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("detail", sa.String(300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["outbox_events.tenant_id", "outbox_events.id"],
            ondelete="CASCADE",
            name="fk_outbox_deliveries_tenant_event",
        ),
        sa.CheckConstraint(
            "outcome IN ('delivered', 'skipped', 'failed')",
            name="ck_outbox_deliveries_outcome_values",
        ),
    )
    op.create_index("ix_outbox_deliveries_event", "outbox_deliveries", ["event_id"])

    op.execute("ALTER TABLE outbox_deliveries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE outbox_deliveries FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON outbox_deliveries "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
    )
    role = _app_role()
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                EXECUTE format(
                    'GRANT SELECT, INSERT, DELETE ON outbox_deliveries TO %I', '{role}'
                );
                -- The dispatcher's retention step deletes dispatched events.
                -- Migration 0007 granted only SELECT, INSERT and UPDATE here,
                -- because nothing deleted from this table at the time.
                EXECUTE format('GRANT DELETE ON outbox_events TO %I', '{role}');
            ELSE
                RAISE NOTICE 'role {role} does not exist; skipping grants';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_table("outbox_deliveries")
    op.drop_constraint("uq_outbox_events_tenant_id_id", "outbox_events", type_="unique")
    op.drop_column("outbox_events", "attempts")
