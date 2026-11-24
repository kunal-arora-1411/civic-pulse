"""Phase 3: teams, assignments, work orders, closure, verification, outbox.

Every new table is tenant-scoped with row-level security. Existing tenants
get the Phase 3 system transitions (docs/api/phase-3-contract.md §9); rows
a tenant already has are left alone.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-26
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen vocabularies (later changes go in later migrations).
OLD_EVENT_TYPES = (
    "created",
    "status_changed",
    "note",
    "report_linked",
    "merged",
    "merged_into",
    "split",
    "category_changed",
    "severity_changed",
    "priority_changed",
)
EVENT_TYPES = (
    *OLD_EVENT_TYPES,
    "assigned",
    "reassigned",
    "work_order_accepted",
    "work_order_declined",
    "work_started",
    "progress",
    "closure_requested",
    "closure_approved",
    "closure_rejected",
    "verification",
    "reopened",
    "closed",
    "report_withdrawn",
)
WORK_ORDER_STATES = (
    "pending_acceptance",
    "accepted",
    "in_progress",
    "completion_requested",
    "done",
    "declined",
    "cancelled",
)
OPEN_STATES = WORK_ORDER_STATES[:4]
SYSTEM_TRANSITIONS = (
    ("reopened", "assigned"),
    ("in_progress", "assigned"),
    ("assigned", "verified"),
    ("assigned", "in_progress"),
    ("in_progress", "pending_verification"),
    ("pending_verification", "resolved"),
    ("pending_verification", "in_progress"),
    ("resolved", "closed"),
    ("resolved", "reopened"),
    ("closed", "reopened"),
)

APP_GRANTS = {
    "teams": "SELECT, INSERT, UPDATE",
    "team_members": "SELECT, INSERT, DELETE",
    "team_jurisdictions": "SELECT, INSERT, DELETE",
    "team_categories": "SELECT, INSERT, DELETE",
    "issue_assignments": "SELECT, INSERT, UPDATE",
    "work_orders": "SELECT, INSERT, UPDATE",
    "closure_requests": "SELECT, INSERT, UPDATE",
    "issue_verifications": "SELECT, INSERT",
    "outbox_events": "SELECT, INSERT, UPDATE",
}
TENANT_SCOPED_TABLES = tuple(APP_GRANTS)
TENANT_PREDICATE = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    " OR current_setting('app.bypass_rls', true) = 'on'"
)


def _in(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _app_role() -> str:
    role = os.environ.get("APP_DB_USER", "civicpulse_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError(f"Refusing to use unexpected role name {role!r}")
    return role


def _uuid_pk() -> sa.Column:
    return sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _tenant(table: str) -> sa.Column:
    return sa.Column(
        "tenant_id",
        sa.Uuid(),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT", name=f"fk_{table}_tenant_id_tenants"),
        nullable=False,
    )


def _user(table: str, column: str) -> sa.Column:
    return sa.Column(
        column,
        sa.Uuid(),
        sa.ForeignKey("users.id", ondelete="SET NULL", name=f"fk_{table}_{column}_users"),
        nullable=True,
    )


def _now(name: str, *, clock: bool = False) -> sa.Column:
    default = sa.text("clock_timestamp()") if clock else sa.func.now()
    return sa.Column(name, sa.DateTime(timezone=True), server_default=default, nullable=False)


def _tenant_fk(
    table: str, column: str, target: str, name: str, ondelete: str = "RESTRICT"
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column],
        [f"{target}.tenant_id", f"{target}.id"],
        ondelete=ondelete,
        name=f"fk_{table}_tenant_{name}",
    )


def upgrade() -> None:
    # --- columns on existing tables -----------------------------------------------------
    op.add_column("categories", sa.Column("closure_policy", postgresql.JSONB(), nullable=True))
    op.add_column(
        "civic_issues", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.drop_constraint("ck_issue_events_type_values", "issue_events", type_="check")
    op.create_check_constraint(
        "ck_issue_events_type_values", "issue_events", f"type IN ({_in(EVENT_TYPES)})"
    )
    op.drop_constraint("ck_tenant_configs_key_values", "tenant_configs", type_="check")
    op.create_check_constraint(
        "ck_tenant_configs_key_values",
        "tenant_configs",
        "key IN ('matching', 'priority', 'closure')",
    )

    # --- teams --------------------------------------------------------------------------
    op.create_table(
        "teams",
        _uuid_pk(),
        _tenant("teams"),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("schedule", postgresql.JSONB(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_teams_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id", "department_id", "name", name="uq_teams_tenant_id_department_id_name"
        ),
        _tenant_fk("teams", "department_id", "departments", "department"),
        sa.CheckConstraint(
            "schedule IS NULL OR jsonb_typeof(schedule) = 'object'",
            name="ck_teams_schedule_is_object",
        ),
    )
    op.create_table(
        "team_members",
        _tenant("team_members"),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("team_role", sa.String(16), nullable=False),
        _now("created_at"),
        sa.PrimaryKeyConstraint("team_id", "user_id", name="pk_team_members"),
        _tenant_fk("team_members", "team_id", "teams", "team", ondelete="CASCADE"),
        _tenant_fk("team_members", "user_id", "users", "user"),
        sa.CheckConstraint(
            "team_role IN ('lead', 'member')", name="ck_team_members_team_role_values"
        ),
    )
    op.create_index("ix_team_members_user_id", "team_members", ["user_id"])
    for table, column, target, name in (
        ("team_jurisdictions", "jurisdiction_id", "jurisdictions", "jurisdiction"),
        ("team_categories", "category_id", "categories", "category"),
    ):
        op.create_table(
            table,
            _tenant(table),
            sa.Column("team_id", sa.Uuid(), nullable=False),
            sa.Column(column, sa.Uuid(), nullable=False),
            sa.PrimaryKeyConstraint("team_id", column, name=f"pk_{table}"),
            _tenant_fk(table, "team_id", "teams", "team", ondelete="CASCADE"),
            _tenant_fk(table, column, target, name),
        )
        op.create_index(f"ix_{table}_{column}", table, [column])

    # --- assignments and work orders ----------------------------------------------------
    op.create_table(
        "issue_assignments",
        _uuid_pk(),
        _tenant("issue_assignments"),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        _user("issue_assignments", "assigned_by"),
        _now("created_at", clock=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(16), nullable=True),
        sa.UniqueConstraint("tenant_id", "id", name="uq_issue_assignments_tenant_id_id"),
        _tenant_fk("issue_assignments", "issue_id", "civic_issues", "issue"),
        _tenant_fk("issue_assignments", "team_id", "teams", "team"),
        _tenant_fk("issue_assignments", "assignee_id", "users", "assignee"),
        sa.CheckConstraint(
            "end_reason IS NULL OR end_reason IN ('reassigned', 'declined')",
            name="ck_issue_assignments_end_reason_values",
        ),
        sa.CheckConstraint(
            "(ended_at IS NULL) = (end_reason IS NULL)",
            name="ck_issue_assignments_ended_has_reason",
        ),
    )
    op.create_index(
        "uq_issue_assignments_open",
        "issue_assignments",
        ["issue_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_index(
        "ix_issue_assignments_issue_created", "issue_assignments", ["issue_id", "created_at"]
    )

    op.create_table(
        "work_orders",
        _uuid_pk(),
        _tenant("work_orders"),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("decline_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_work_orders_tenant_id_id"),
        _tenant_fk("work_orders", "issue_id", "civic_issues", "issue"),
        _tenant_fk("work_orders", "assignment_id", "issue_assignments", "assignment"),
        _tenant_fk("work_orders", "assignee_id", "users", "assignee"),
        sa.CheckConstraint(
            f"state IN ({_in(WORK_ORDER_STATES)})", name="ck_work_orders_state_values"
        ),
        sa.CheckConstraint(
            "state <> 'declined' OR decline_reason IS NOT NULL",
            name="ck_work_orders_declined_reason",
        ),
        sa.CheckConstraint("version >= 1", name="ck_work_orders_version_positive"),
    )
    op.create_index(
        "ix_work_orders_assignee_state", "work_orders", ["tenant_id", "assignee_id", "state"]
    )
    op.create_index("ix_work_orders_issue_id", "work_orders", ["issue_id"])
    op.create_index(
        "uq_work_orders_open_per_issue",
        "work_orders",
        ["issue_id"],
        unique=True,
        postgresql_where=sa.text(f"state IN ({_in(OPEN_STATES)})"),
    )

    # --- media: field evidence ----------------------------------------------------------
    op.add_column("media_assets", sa.Column("phase", sa.String(8), nullable=True))
    op.add_column("media_assets", sa.Column("work_order_id", sa.Uuid(), nullable=True))
    op.drop_constraint("ck_media_assets_purpose_values", "media_assets", type_="check")
    op.create_check_constraint(
        "ck_media_assets_purpose_values",
        "media_assets",
        "purpose IN ('report_evidence', 'work_evidence')",
    )
    op.create_check_constraint(
        "ck_media_assets_phase_for_work_evidence",
        "media_assets",
        "(purpose = 'work_evidence') = (phase IS NOT NULL AND phase IN ('before', 'after'))",
    )
    op.create_check_constraint(
        "ck_media_assets_work_order_evidence_only",
        "media_assets",
        "work_order_id IS NULL OR purpose = 'work_evidence'",
    )
    op.create_foreign_key(
        "fk_media_assets_tenant_work_order",
        "media_assets",
        "work_orders",
        ["tenant_id", "work_order_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_media_assets_work_order_id", "media_assets", ["work_order_id"])

    # --- closure and verification -------------------------------------------------------
    op.create_table(
        "closure_requests",
        _uuid_pk(),
        _tenant("closure_requests"),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("work_order_id", sa.Uuid(), nullable=True),
        _user("closure_requests", "requested_by"),
        sa.Column("reason_code", sa.String(50), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        _user("closure_requests", "decided_by"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        _now("created_at", clock=True),
        sa.UniqueConstraint("tenant_id", "id", name="uq_closure_requests_tenant_id_id"),
        _tenant_fk("closure_requests", "issue_id", "civic_issues", "issue"),
        _tenant_fk("closure_requests", "work_order_id", "work_orders", "work_order"),
        sa.CheckConstraint(
            "state IN ('pending', 'approved', 'rejected')", name="ck_closure_requests_state_values"
        ),
    )
    op.create_index(
        "uq_closure_requests_pending",
        "closure_requests",
        ["issue_id"],
        unique=True,
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_table(
        "issue_verifications",
        _uuid_pk(),
        _tenant("issue_verifications"),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("closure_request_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        _now("created_at"),
        sa.UniqueConstraint(
            "closure_request_id",
            "user_id",
            name="uq_issue_verifications_closure_request_id_user_id",
        ),
        _tenant_fk("issue_verifications", "issue_id", "civic_issues", "issue"),
        _tenant_fk("issue_verifications", "closure_request_id", "closure_requests", "closure"),
        _tenant_fk("issue_verifications", "user_id", "users", "user"),
        sa.CheckConstraint(
            "outcome IN ('resolved', 'unresolved')", name="ck_issue_verifications_outcome_values"
        ),
    )
    op.create_index("ix_issue_verifications_issue_id", "issue_verifications", ["issue_id"])

    # --- outbox -------------------------------------------------------------------------
    op.create_table(
        "outbox_events",
        _uuid_pk(),
        _tenant("outbox_events"),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("aggregate_type", sa.String(32), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        _now("created_at", clock=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_outbox_events_undispatched",
        "outbox_events",
        ["created_at"],
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )

    # --- row-level security and grants --------------------------------------------------
    for table in TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )
    role = _app_role()
    grants = "\n".join(
        f"EXECUTE format('GRANT {privileges} ON {table} TO %I', '{role}');"
        for table, privileges in APP_GRANTS.items()
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                {grants}
            ELSE
                RAISE NOTICE 'role {role} does not exist; skipping grants';
            END IF;
        END
        $$
        """
    )

    # --- Phase 3 system transitions for tenants that already exist ----------------------
    rows = ",\n".join(f"('{src}', '{dst}')" for src, dst in SYSTEM_TRANSITIONS)
    op.execute(
        f"""
        INSERT INTO status_transitions
            (tenant_id, from_status, to_status, allowed_roles, requires_reason, system_only)
        SELECT t.id, d.from_status, d.to_status, '{{}}'::varchar[], false, true
        FROM tenants t
        CROSS JOIN (VALUES {rows}) AS d(from_status, to_status)
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    pairs = " OR ".join(
        f"(from_status = '{src}' AND to_status = '{dst}' AND system_only)"
        for src, dst in SYSTEM_TRANSITIONS
    )
    op.execute(f"DELETE FROM status_transitions WHERE {pairs}")
    op.drop_index("ix_media_assets_work_order_id", "media_assets")
    op.drop_constraint("fk_media_assets_tenant_work_order", "media_assets", type_="foreignkey")
    for table in (
        "outbox_events",
        "issue_verifications",
        "closure_requests",
        "work_orders",
        "issue_assignments",
        "team_categories",
        "team_jurisdictions",
        "team_members",
        "teams",
    ):
        op.drop_table(table)
    op.execute("DELETE FROM media_assets WHERE purpose = 'work_evidence'")
    op.drop_constraint("ck_media_assets_work_order_evidence_only", "media_assets", type_="check")
    op.drop_constraint("ck_media_assets_phase_for_work_evidence", "media_assets", type_="check")
    op.drop_constraint("ck_media_assets_purpose_values", "media_assets", type_="check")
    op.create_check_constraint(
        "ck_media_assets_purpose_values", "media_assets", "purpose IN ('report_evidence')"
    )
    op.drop_column("media_assets", "work_order_id")
    op.drop_column("media_assets", "phase")
    op.execute("DELETE FROM tenant_configs WHERE key = 'closure'")
    op.drop_constraint("ck_tenant_configs_key_values", "tenant_configs", type_="check")
    op.create_check_constraint(
        "ck_tenant_configs_key_values", "tenant_configs", "key IN ('matching', 'priority')"
    )
    op.execute(f"DELETE FROM issue_events WHERE type NOT IN ({_in(OLD_EVENT_TYPES)})")
    op.drop_constraint("ck_issue_events_type_values", "issue_events", type_="check")
    op.create_check_constraint(
        "ck_issue_events_type_values", "issue_events", f"type IN ({_in(OLD_EVENT_TYPES)})"
    )
    op.drop_column("civic_issues", "resolved_at")
    op.drop_column("categories", "closure_policy")
