"""Severity and priority: rule-based columns replacing the Phase 1 strings,
category severity rules, and places of interest.

Phase 1 had free-text `severity` and `priority` columns that nothing in the
product could set. A value that names a level is kept as a manual override
(someone chose it, and an override is what stays put); anything else is
dropped. Every issue starts at `medium` from the rules and with no
computed priority: the application recomputes issues whose
`priority_computed_at` is NULL within a minute of starting (the matching
watchdog), and nightly.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-24
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEVELS = ("low", "medium", "high", "critical")
PLACE_KINDS = ("school", "hospital", "bus_stop", "market", "other")
CARRIED_OVER = "Set before severity and priority rules existed (Phase 1)."

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


def upgrade() -> None:
    levels = _in(LEVELS)

    # --- categories ----------------------------------------------------------------
    op.add_column("categories", sa.Column("severity_rules", postgresql.JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_categories_severity_rules_is_object",
        "categories",
        "severity_rules IS NULL OR jsonb_typeof(severity_rules) = 'object'",
    )

    # --- civic_issues: carry the Phase 1 strings over, then replace them ------------
    op.alter_column("civic_issues", "severity", new_column_name="phase1_severity")
    op.alter_column("civic_issues", "priority", new_column_name="phase1_priority")
    op.add_column(
        "civic_issues",
        sa.Column("severity", sa.String(16), server_default=sa.text("'medium'"), nullable=False),
    )
    op.add_column(
        "civic_issues",
        sa.Column(
            "severity_source", sa.String(16), server_default=sa.text("'rule'"), nullable=False
        ),
    )
    op.add_column("civic_issues", sa.Column("severity_reason", sa.Text(), nullable=True))
    op.add_column("civic_issues", sa.Column("priority_score", sa.Numeric(5, 2), nullable=True))
    op.add_column("civic_issues", sa.Column("priority_band", sa.String(16), nullable=True))
    op.add_column("civic_issues", sa.Column("priority_override_band", sa.String(16), nullable=True))
    op.add_column("civic_issues", sa.Column("priority_override_reason", sa.Text(), nullable=True))
    op.add_column("civic_issues", sa.Column("priority_factors", postgresql.JSONB(), nullable=True))
    op.add_column(
        "civic_issues",
        sa.Column("priority_computed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            f"""
            UPDATE civic_issues
               SET severity = lower(btrim(phase1_severity)),
                   severity_source = 'override',
                   severity_reason = :reason
             WHERE lower(btrim(phase1_severity)) IN ({levels})
            """
        ).bindparams(reason=CARRIED_OVER)
    )
    op.execute(
        sa.text(
            f"""
            UPDATE civic_issues
               SET priority_override_band = lower(btrim(phase1_priority)),
                   priority_override_reason = :reason
             WHERE lower(btrim(phase1_priority)) IN ({levels})
            """
        ).bindparams(reason=CARRIED_OVER)
    )
    op.drop_column("civic_issues", "phase1_severity")
    op.drop_column("civic_issues", "phase1_priority")

    op.create_check_constraint(
        "ck_civic_issues_severity_values", "civic_issues", f"severity IN ({levels})"
    )
    op.create_check_constraint(
        "ck_civic_issues_severity_source_values",
        "civic_issues",
        "severity_source IN ('rule', 'override')",
    )
    op.create_check_constraint(
        "ck_civic_issues_override_has_reason",
        "civic_issues",
        "severity_source = 'rule' OR severity_reason IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_civic_issues_priority_band_values",
        "civic_issues",
        f"priority_band IS NULL OR priority_band IN ({levels})",
    )
    op.create_check_constraint(
        "ck_civic_issues_priority_override_values",
        "civic_issues",
        f"priority_override_band IS NULL OR priority_override_band IN ({levels})",
    )
    op.create_check_constraint(
        "ck_civic_issues_priority_override_has_reason",
        "civic_issues",
        "(priority_override_band IS NULL) = (priority_override_reason IS NULL)",
    )
    op.create_check_constraint(
        "ck_civic_issues_priority_score_range",
        "civic_issues",
        "priority_score IS NULL OR priority_score BETWEEN 0 AND 100",
    )
    op.create_index(
        "ix_civic_issues_tenant_priority_score", "civic_issues", ["tenant_id", "priority_score"]
    )
    op.create_index(
        "ix_civic_issues_priority_pending",
        "civic_issues",
        ["created_at"],
        postgresql_where=sa.text("priority_computed_at IS NULL"),
    )

    # --- places_of_interest -----------------------------------------------------------
    op.create_table(
        "places_of_interest",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(
                "tenants.id", ondelete="RESTRICT", name="fk_places_of_interest_tenant_id_tenants"
            ),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.Geometry("POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"kind IN ({_in(PLACE_KINDS)})", name="ck_places_of_interest_kind_values"
        ),
    )
    op.create_index(
        "ix_places_of_interest_geom", "places_of_interest", ["geom"], postgresql_using="gist"
    )
    op.execute("ALTER TABLE places_of_interest ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE places_of_interest FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON places_of_interest "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
    )
    role = _app_role()
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON places_of_interest TO %I',
                               '{role}');
            ELSE
                RAISE NOTICE 'role {role} does not exist; skipping grants';
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_table("places_of_interest")
    op.drop_index("ix_civic_issues_priority_pending", "civic_issues")
    op.drop_index("ix_civic_issues_tenant_priority_score", "civic_issues")
    for name in (
        "ck_civic_issues_priority_score_range",
        "ck_civic_issues_priority_override_has_reason",
        "ck_civic_issues_priority_override_values",
        "ck_civic_issues_priority_band_values",
        "ck_civic_issues_override_has_reason",
        "ck_civic_issues_severity_source_values",
        "ck_civic_issues_severity_values",
    ):
        op.drop_constraint(name, "civic_issues", type_="check")
    op.add_column("civic_issues", sa.Column("phase1_priority", sa.String(16), nullable=True))
    op.execute("UPDATE civic_issues SET phase1_priority = priority_override_band")
    for column in (
        "priority_computed_at",
        "priority_factors",
        "priority_override_reason",
        "priority_override_band",
        "priority_band",
        "priority_score",
        "severity_reason",
        "severity_source",
    ):
        op.drop_column("civic_issues", column)
    op.alter_column("civic_issues", "severity", new_column_name="phase1_severity")
    op.alter_column("civic_issues", "phase1_severity", server_default=None, nullable=True)
    op.alter_column("civic_issues", "phase1_severity", new_column_name="severity")
    op.alter_column("civic_issues", "phase1_priority", new_column_name="priority")
    op.drop_constraint("ck_categories_severity_rules_is_object", "categories", type_="check")
    op.drop_column("categories", "severity_rules")
