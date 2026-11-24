"""Community support: citizens who face an issue too ("+1") and follow it.

One row per user per issue, tenant-scoped with row-level security. The
issue keeps a denormalised `support_count` so lists, the public tracker and
the priority rules can read it without a join.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-24
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
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
        "civic_issues",
        sa.Column("support_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint(
        "ck_civic_issues_support_count_non_negative", "civic_issues", "support_count >= 0"
    )
    op.create_table(
        "issue_supports",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(
                "tenants.id", ondelete="RESTRICT", name="fk_issue_supports_tenant_id_tenants"
            ),
            nullable=False,
        ),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("issue_id", "user_id", name="uq_issue_supports_issue_id_user_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "issue_id"],
            ["civic_issues.tenant_id", "civic_issues.id"],
            ondelete="CASCADE",
            name="fk_issue_supports_tenant_issue",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
            name="fk_issue_supports_tenant_user",
        ),
    )
    op.create_index("ix_issue_supports_user_id", "issue_supports", ["user_id"])

    op.execute("ALTER TABLE issue_supports ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE issue_supports FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON issue_supports "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
    )
    role = _app_role()
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                EXECUTE format('GRANT SELECT, INSERT, DELETE ON issue_supports TO %I', '{role}');
            ELSE
                RAISE NOTICE 'role {role} does not exist; skipping grants';
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_table("issue_supports")
    op.drop_constraint("ck_civic_issues_support_count_non_negative", "civic_issues", type_="check")
    op.drop_column("civic_issues", "support_count")
