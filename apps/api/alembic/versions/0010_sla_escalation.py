"""SLA targets and escalation (FR-056, FR-057, AC-09).

A tenant sets a resolution target per category, optionally narrowed to a
priority band. Each open issue carries the deadline that applies to it
(`due_at`), when it was first seen past that deadline (`breached_at`) and how
far the breach has been escalated (`escalation_level`).

A trigger, not service code, keeps `due_at` current, so that every path that
creates an issue or changes its category, priority or status (API, workers,
consolidation, the seed) schedules it the same way. The clock starts when
the issue is created and restarts when it is reopened; it freezes once the
issue is resolved, rejected or closed, so compliance can compare the
resolution time against the deadline that applied.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-24
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    " OR current_setting('app.bypass_rls', true) = 'on'"
)
BANDS = ("low", "medium", "high", "critical")
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
EVENT_TYPES = (*OLD_EVENT_TYPES, "sla_breached", "sla_escalated")
OLD_KINDS = ("report_new_issue", "report_linked", "issue_status", "review_task", "assignment")
KINDS = (*OLD_KINDS, "sla_breach")

SCHEDULE = r"""
CREATE FUNCTION sla_schedule() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE
    hours integer;
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.sla_started_at := coalesce(NEW.sla_started_at, NEW.created_at, clock_timestamp());
    ELSIF NEW.status = 'reopened' AND OLD.status IS DISTINCT FROM 'reopened' THEN
        NEW.sla_started_at := clock_timestamp();
        NEW.breached_at := NULL;
        NEW.escalation_level := 0;
    END IF;

    -- Finished issues keep the deadline they had: the clock is paused.
    IF NEW.status IN ('resolved', 'rejected', 'closed') THEN
        RETURN NEW;
    END IF;

    SELECT t.resolve_hours INTO hours
    FROM sla_targets t
    WHERE t.tenant_id = NEW.tenant_id
      AND t.category_id = NEW.category_id
      AND (t.priority_band IS NULL
           OR t.priority_band = coalesce(NEW.priority_override_band, NEW.priority_band))
    ORDER BY t.priority_band NULLS LAST
    LIMIT 1;

    IF hours IS NULL THEN
        NEW.due_at := NULL;
    ELSE
        NEW.due_at := NEW.sla_started_at + make_interval(hours => hours);
    END IF;
    -- A later deadline (a lower band, a relaxed target) lifts the breach.
    IF NEW.due_at IS NULL OR NEW.due_at > clock_timestamp() THEN
        NEW.breached_at := NULL;
        NEW.escalation_level := 0;
    END IF;
    RETURN NEW;
END
$fn$
--;;
CREATE TRIGGER sla_schedule
    BEFORE INSERT OR UPDATE OF category_id, priority_band, priority_override_band, status,
        sla_started_at
    ON civic_issues FOR EACH ROW EXECUTE FUNCTION sla_schedule()
"""


def _in(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _app_role() -> str:
    role = os.environ.get("APP_DB_USER", "civicpulse_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError(f"Refusing to use unexpected role name {role!r}")
    return role


def upgrade() -> None:
    op.create_table(
        "sla_targets",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(
                "tenants.id", ondelete="RESTRICT", name="fk_sla_targets_tenant_id_tenants"
            ),
            nullable=False,
        ),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("priority_band", sa.String(16), nullable=True),
        sa.Column("resolve_hours", sa.Integer(), nullable=False),
        sa.Column("escalate_after_hours", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sla_targets"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            ondelete="CASCADE",
            name="fk_sla_targets_tenant_category",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_sla_targets_updated_by_users",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "category_id",
            "priority_band",
            name="uq_sla_targets_tenant_id_category_id_priority_band",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint(
            f"priority_band IS NULL OR priority_band IN ({_in(BANDS)})",
            name="ck_sla_targets_priority_band_values",
        ),
        sa.CheckConstraint(
            "resolve_hours BETWEEN 1 AND 8760", name="ck_sla_targets_resolve_hours_range"
        ),
        sa.CheckConstraint(
            "escalate_after_hours BETWEEN 1 AND 8760",
            name="ck_sla_targets_escalate_after_hours_range",
        ),
    )
    op.execute("ALTER TABLE sla_targets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sla_targets FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON sla_targets "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
    )
    role = _app_role()
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                EXECUTE format(
                    'GRANT SELECT, INSERT, UPDATE, DELETE ON sla_targets TO %I', '{role}');
            ELSE
                RAISE NOTICE 'role {role} does not exist; skipping grants';
            END IF;
        END
        $$
        """
    )

    op.add_column(
        "civic_issues", sa.Column("sla_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("civic_issues", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "civic_issues", sa.Column("breached_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "civic_issues",
        sa.Column(
            "escalation_level", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_civic_issues_escalation_level_range", "civic_issues", "escalation_level BETWEEN 0 AND 2"
    )
    op.create_index(
        "ix_civic_issues_due_at",
        "civic_issues",
        ["due_at"],
        postgresql_where=sa.text("due_at IS NOT NULL"),
    )
    op.execute("UPDATE civic_issues SET sla_started_at = created_at")

    op.drop_constraint("ck_issue_events_type_values", "issue_events", type_="check")
    op.create_check_constraint(
        "ck_issue_events_type_values", "issue_events", f"type IN ({_in(EVENT_TYPES)})"
    )
    op.drop_constraint("ck_notifications_kind_values", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notifications_kind_values", "notifications", f"kind IN ({_in(KINDS)})"
    )
    for statement in SCHEDULE.split("--;;"):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS sla_schedule ON civic_issues")
    op.execute("DROP FUNCTION IF EXISTS sla_schedule()")
    op.execute("DELETE FROM notifications WHERE kind = 'sla_breach'")
    op.execute("DELETE FROM issue_events WHERE type IN ('sla_breached', 'sla_escalated')")
    op.drop_constraint("ck_notifications_kind_values", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notifications_kind_values", "notifications", f"kind IN ({_in(OLD_KINDS)})"
    )
    op.drop_constraint("ck_issue_events_type_values", "issue_events", type_="check")
    op.create_check_constraint(
        "ck_issue_events_type_values", "issue_events", f"type IN ({_in(OLD_EVENT_TYPES)})"
    )
    op.drop_index("ix_civic_issues_due_at", table_name="civic_issues")
    op.drop_constraint("ck_civic_issues_escalation_level_range", "civic_issues", type_="check")
    for column in ("escalation_level", "breached_at", "due_at", "sla_started_at"):
        op.drop_column("civic_issues", column)
    op.drop_table("sla_targets")
