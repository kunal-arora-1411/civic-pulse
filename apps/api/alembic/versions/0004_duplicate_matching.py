"""Duplicate matching: report matching state, match decisions, review
tasks, merges, related issues and per-tenant configuration.

Reports stop getting an issue at submission: `issue_id` (already nullable)
is NULL exactly while matching is pending or in review, which a check
constraint now enforces. Every Phase 1 report already has its own issue,
so all of them become `new_issue`.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-24
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen vocabularies (later changes go in later migrations).
OLD_EVENT_TYPES = ("created", "status_changed", "note")
EVENT_TYPES = (
    *OLD_EVENT_TYPES,
    "report_linked",
    "merged",
    "merged_into",
    "split",
    "category_changed",
    "severity_changed",
    "priority_changed",
)
CATEGORY_SOURCES = ("citizen", "ai_accepted", "ai_corrected", "operator")
MATCHING_STATUSES = ("pending", "review", "linked", "new_issue")
DECISIONS = (
    "auto_linked",
    "sent_to_review",
    "rejected_candidate",
    "chosen_by_reviewer",
    "not_chosen",
)

APP_GRANTS = {
    "match_decisions": "SELECT, INSERT, UPDATE",
    "review_tasks": "SELECT, INSERT, UPDATE",
    "issue_relations": "SELECT, INSERT, DELETE",
    "tenant_configs": "SELECT, INSERT, UPDATE",
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


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _tenant_fk(table: str, column: str, target: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column],
        [f"{target}.tenant_id", f"{target}.id"],
        ondelete="RESTRICT",
        name=f"fk_{table}_tenant_{name}",
    )


def upgrade() -> None:
    # --- reports -----------------------------------------------------------------
    op.add_column("reports", sa.Column("classification_id", sa.Uuid(), nullable=True))
    op.add_column(
        "reports",
        sa.Column(
            "category_source",
            sa.String(16),
            server_default=sa.text("'citizen'"),
            nullable=False,
        ),
    )
    op.add_column("reports", sa.Column("matching_status", sa.String(16), nullable=True))
    op.execute(
        "UPDATE reports SET matching_status = "
        "CASE WHEN issue_id IS NULL THEN 'pending' ELSE 'new_issue' END"
    )
    op.alter_column("reports", "matching_status", nullable=False)
    op.create_foreign_key(
        "fk_reports_tenant_classification",
        "reports",
        "classifications",
        ["tenant_id", "classification_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_reports_category_source_values",
        "reports",
        f"category_source IN ({_in(CATEGORY_SOURCES)})",
    )
    op.create_check_constraint(
        "ck_reports_matching_status_values",
        "reports",
        f"matching_status IN ({_in(MATCHING_STATUSES)})",
    )
    op.create_check_constraint(
        "ck_reports_issue_matches_status",
        "reports",
        "(matching_status IN ('pending', 'review')) = (issue_id IS NULL)",
    )
    op.create_index(
        "ix_reports_matching_pending",
        "reports",
        ["created_at"],
        postgresql_where=sa.text("matching_status = 'pending'"),
    )

    # --- civic_issues: merges --------------------------------------------------------
    op.add_column("civic_issues", sa.Column("merged_into_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_civic_issues_tenant_merged_into",
        "civic_issues",
        "civic_issues",
        ["tenant_id", "merged_into_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_civic_issues_not_merged_into_self",
        "civic_issues",
        "merged_into_id IS NULL OR merged_into_id <> id",
    )
    op.create_index("ix_civic_issues_merged_into_id", "civic_issues", ["merged_into_id"])

    # --- issue_events: new event types, the other issue, details --------------------
    op.add_column("issue_events", sa.Column("related_issue_id", sa.Uuid(), nullable=True))
    op.add_column("issue_events", sa.Column("data", postgresql.JSONB(), nullable=True))
    # A merge or split writes several events in one transaction; now() would
    # give them all the same time and the timeline no stable order.
    op.alter_column("issue_events", "created_at", server_default=sa.text("clock_timestamp()"))
    op.create_foreign_key(
        "fk_issue_events_tenant_related_issue",
        "issue_events",
        "civic_issues",
        ["tenant_id", "related_issue_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_issue_events_type_values", "issue_events", type_="check")
    op.create_check_constraint(
        "ck_issue_events_type_values", "issue_events", f"type IN ({_in(EVENT_TYPES)})"
    )

    # --- match_decisions -------------------------------------------------------------
    op.create_table(
        "match_decisions",
        _uuid_pk(),
        _tenant("match_decisions"),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_issue_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("signals", postgresql.JSONB(), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        _now("created_at"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feedback", sa.String(16), nullable=True),
        sa.Column("feedback_by", sa.Uuid(), nullable=True),
        sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feedback_note", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "report_id",
            "candidate_issue_id",
            name="uq_match_decisions_report_id_candidate_issue_id",
        ),
        _tenant_fk("match_decisions", "report_id", "reports", "report"),
        _tenant_fk("match_decisions", "candidate_issue_id", "civic_issues", "candidate_issue"),
        _tenant_fk("match_decisions", "decided_by", "users", "decided_by"),
        _tenant_fk("match_decisions", "feedback_by", "users", "feedback_by"),
        sa.CheckConstraint(
            f"decision IN ({_in(DECISIONS)})", name="ck_match_decisions_decision_values"
        ),
        sa.CheckConstraint(
            "feedback IS NULL OR feedback IN ('correct', 'incorrect')",
            name="ck_match_decisions_feedback_values",
        ),
        sa.CheckConstraint("rank >= 1", name="ck_match_decisions_rank_positive"),
        sa.CheckConstraint("score BETWEEN 0 AND 1", name="ck_match_decisions_score_range"),
    )
    op.create_index(
        "ix_match_decisions_candidate_issue_id", "match_decisions", ["candidate_issue_id"]
    )
    op.create_index(
        "ix_match_decisions_tenant_created", "match_decisions", ["tenant_id", "created_at"]
    )

    # --- review_tasks ------------------------------------------------------------------
    op.create_table(
        "review_tasks",
        _uuid_pk(),
        _tenant("review_tasks"),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("resolution", sa.String(16), nullable=True),
        sa.Column("resolved_issue_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        _tenant_fk("review_tasks", "report_id", "reports", "report"),
        _tenant_fk("review_tasks", "resolved_issue_id", "civic_issues", "resolved_issue"),
        _tenant_fk("review_tasks", "resolved_by", "users", "resolved_by"),
        sa.CheckConstraint("status IN ('open', 'resolved')", name="ck_review_tasks_status_values"),
        sa.CheckConstraint(
            "resolution IS NULL OR resolution IN ('linked', 'new_issue')",
            name="ck_review_tasks_resolution_values",
        ),
        sa.CheckConstraint(
            "(status = 'open') = (resolution IS NULL AND resolved_at IS NULL)",
            name="ck_review_tasks_resolved_has_resolution",
        ),
    )
    op.create_index(
        "uq_review_tasks_open_report",
        "review_tasks",
        ["report_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_review_tasks_tenant_status_created",
        "review_tasks",
        ["tenant_id", "status", "created_at"],
    )

    # --- issue_relations ------------------------------------------------------------
    op.create_table(
        "issue_relations",
        _tenant("issue_relations"),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("related_issue_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="SET NULL", name="fk_issue_relations_created_by_users"
            ),
            nullable=True,
        ),
        _now("created_at"),
        sa.PrimaryKeyConstraint("issue_id", "related_issue_id", name="pk_issue_relations"),
        _tenant_fk("issue_relations", "issue_id", "civic_issues", "issue"),
        _tenant_fk("issue_relations", "related_issue_id", "civic_issues", "related_issue"),
        sa.CheckConstraint("issue_id < related_issue_id", name="ck_issue_relations_ordered_pair"),
    )
    op.create_index("ix_issue_relations_related_issue_id", "issue_relations", ["related_issue_id"])

    # --- tenant_configs ----------------------------------------------------------------
    op.create_table(
        "tenant_configs",
        _tenant("tenant_configs"),
        sa.Column("key", sa.String(32), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_by",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="SET NULL", name="fk_tenant_configs_updated_by_users"
            ),
            nullable=True,
        ),
        _now("created_at"),
        _now("updated_at"),
        sa.PrimaryKeyConstraint("tenant_id", "key", name="pk_tenant_configs"),
        sa.CheckConstraint("key IN ('matching', 'priority')", name="ck_tenant_configs_key_values"),
        sa.CheckConstraint(
            "jsonb_typeof(value) = 'object'", name="ck_tenant_configs_value_is_object"
        ),
    )

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


def downgrade() -> None:
    for table in ("tenant_configs", "issue_relations", "review_tasks", "match_decisions"):
        op.drop_table(table)
    op.execute(f"DELETE FROM issue_events WHERE type NOT IN ({_in(OLD_EVENT_TYPES)})")
    op.drop_constraint("ck_issue_events_type_values", "issue_events", type_="check")
    op.create_check_constraint(
        "ck_issue_events_type_values", "issue_events", f"type IN ({_in(OLD_EVENT_TYPES)})"
    )
    op.drop_constraint("fk_issue_events_tenant_related_issue", "issue_events", type_="foreignkey")
    op.alter_column("issue_events", "created_at", server_default=sa.text("now()"))
    op.drop_column("issue_events", "data")
    op.drop_column("issue_events", "related_issue_id")
    op.drop_index("ix_civic_issues_merged_into_id", "civic_issues")
    op.drop_constraint("ck_civic_issues_not_merged_into_self", "civic_issues", type_="check")
    op.drop_constraint("fk_civic_issues_tenant_merged_into", "civic_issues", type_="foreignkey")
    op.drop_column("civic_issues", "merged_into_id")
    op.drop_index("ix_reports_matching_pending", "reports")
    for name in (
        "ck_reports_issue_matches_status",
        "ck_reports_matching_status_values",
        "ck_reports_category_source_values",
    ):
        op.drop_constraint(name, "reports", type_="check")
    op.drop_constraint("fk_reports_tenant_classification", "reports", type_="foreignkey")
    op.drop_column("reports", "matching_status")
    op.drop_column("reports", "category_source")
    op.drop_column("reports", "classification_id")
