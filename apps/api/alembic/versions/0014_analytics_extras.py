"""Saved analytics views and public service announcements.

`analytics_views` keeps a staff member's named filter combinations for the
dashboard (FR-077). They are personal: the service only ever reads the
caller's own rows, and RLS keeps them inside the tenant.

`announcements` are notices an administrator publishes for a ward or the
whole city, optionally about one category: planned works, outages, advisories (FR-087). They are shown on
the public tracker, so they carry their text in English and Hindi and a
start and end time. Withdrawing one keeps the row (and its audit trail).

Revision ID: 0014
Revises: 0011
Create Date: 2026-11-26
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0011"
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


def _tenant_fk(table: str) -> sa.Column[uuid.UUID]:
    return sa.Column(
        "tenant_id",
        sa.Uuid(),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT", name=f"fk_{table}_tenant_id_tenants"),
        nullable=False,
    )


def _timestamps() -> list[sa.Column[datetime]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _isolate(table: str, grants: str) -> None:
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
        "analytics_views",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant_fk("analytics_views"),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("filters", postgresql.JSONB(), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
            name="fk_analytics_views_tenant_user",
        ),
    )
    # Names are unique per person regardless of case, and a person has at
    # most one default view.
    op.create_index(
        "uq_analytics_views_user_name",
        "analytics_views",
        ["user_id", sa.text("lower(name)")],
        unique=True,
    )
    op.create_index(
        "uq_analytics_views_user_default",
        "analytics_views",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    _isolate("analytics_views", "SELECT, INSERT, UPDATE, DELETE")

    op.create_table(
        "announcements",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant_fk("announcements"),
        sa.Column("ward_id", sa.Uuid(), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("title_i18n", postgresql.JSONB(), nullable=False),
        sa.Column("body_i18n", postgresql.JSONB(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "id", name="uq_announcements_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ward_id"],
            ["jurisdictions.tenant_id", "jurisdictions.id"],
            ondelete="RESTRICT",
            name="fk_announcements_tenant_ward",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            ondelete="RESTRICT",
            name="fk_announcements_tenant_category",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
            name="fk_announcements_tenant_created_by",
        ),
        sa.CheckConstraint(
            "kind IN ('planned_works', 'outage', 'advisory')",
            name="ck_announcements_kind_values",
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_announcements_period"),
    )
    op.create_index("ix_announcements_tenant_ends_at", "announcements", ["tenant_id", "ends_at"])
    # Never deleted: a withdrawn notice keeps its row and its audit trail.
    _isolate("announcements", "SELECT, INSERT, UPDATE")


def downgrade() -> None:
    op.drop_table("announcements")
    op.drop_table("analytics_views")
