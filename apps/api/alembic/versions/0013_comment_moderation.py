"""Citizen comments on issues, held for moderation, and flags on them.

Comments (FR-017) stay private to their author until a moderator approves
them; citizens can flag approved ones (FR-086), and enough flags send a
comment back to the moderation queue. Both tables are tenant-scoped with
forced row-level security.

Numbered 0013 by agreement with the other Phase work in flight; it follows
the head on main when it was written, 0015.

Revision ID: 0013
Revises: 0015
Create Date: 2026-11-26
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0015"
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


def _tenant(table: str) -> sa.Column:
    return sa.Column(
        "tenant_id",
        sa.Uuid(),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT", name=f"fk_{table}_tenant_id_tenants"),
        nullable=False,
    )


def _secure(table: str, grants: str) -> None:
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
                EXECUTE format('GRANT {grants} ON {table} TO %I', '{role}');
            ELSE
                RAISE NOTICE 'role {role} does not exist; skipping grants';
            END IF;
        END
        $$
        """
    )


def upgrade() -> None:
    op.create_table(
        "issue_comments",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant("issue_comments"),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("state", sa.String(10), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("flag_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "moderated_by",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="SET NULL", name="fk_issue_comments_moderated_by_users"
            ),
            nullable=True,
        ),
        sa.Column("moderated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("moderation_reason", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_issue_comments_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "issue_id"],
            ["civic_issues.tenant_id", "civic_issues.id"],
            ondelete="CASCADE",
            name="fk_issue_comments_tenant_issue",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "author_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
            name="fk_issue_comments_tenant_author",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'approved', 'rejected')",
            name="ck_issue_comments_state_values",
        ),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 1000", name="ck_issue_comments_body_length"
        ),
        sa.CheckConstraint("flag_count >= 0", name="ck_issue_comments_flag_count_non_negative"),
    )
    op.create_index("ix_issue_comments_issue_created", "issue_comments", ["issue_id", "created_at"])
    op.create_index("ix_issue_comments_state_created", "issue_comments", ["state", "created_at"])
    op.create_index(
        "ix_issue_comments_author_created", "issue_comments", ["author_id", "created_at"]
    )
    _secure("issue_comments", "SELECT, INSERT, UPDATE")

    op.create_table(
        "comment_flags",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant("comment_flags"),
        sa.Column("comment_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("comment_id", "user_id", name="uq_comment_flags_comment_id_user_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "comment_id"],
            ["issue_comments.tenant_id", "issue_comments.id"],
            ondelete="CASCADE",
            name="fk_comment_flags_tenant_comment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
            name="fk_comment_flags_tenant_user",
        ),
    )
    _secure("comment_flags", "SELECT, INSERT, DELETE")


def downgrade() -> None:
    op.drop_table("comment_flags")
    op.drop_table("issue_comments")
