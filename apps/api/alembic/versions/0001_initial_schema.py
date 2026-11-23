"""Initial schema: tenancy, identity, RBAC, organisation, auth and audit.

Revision ID: 0001
Revises:
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

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXTENSIONS = ("pgcrypto", "postgis", "vector", "h3")

ROLE_VALUES = (
    "citizen",
    "community_contributor",
    "operator",
    "supervisor",
    "field_worker",
    "municipal_admin",
    "platform_admin",
)
JURISDICTION_KIND_VALUES = ("city", "zone", "ward", "service_area")

# What the application role may do to each table. audit_events is
# insert-only at the privilege level as well as by trigger.
APP_GRANTS = {
    "tenants": "SELECT, INSERT, UPDATE",
    "users": "SELECT, INSERT, UPDATE, DELETE",
    "user_roles": "SELECT, INSERT, UPDATE, DELETE",
    "departments": "SELECT, INSERT, UPDATE, DELETE",
    "jurisdictions": "SELECT, INSERT, UPDATE, DELETE",
    "otp_challenges": "SELECT, INSERT, UPDATE, DELETE",
    "auth_sessions": "SELECT, INSERT, UPDATE, DELETE",
    "idempotency_keys": "SELECT, INSERT, UPDATE, DELETE",
    "audit_events": "SELECT, INSERT",
}


def _app_role() -> str:
    role = os.environ.get("APP_DB_USER", "civicpulse_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError(f"Refusing to use unexpected role name {role!r}")
    return role


def _uuid_pk() -> sa.Column:
    return sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    for extension in EXTENSIONS:
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")

    user_role = postgresql.ENUM(*ROLE_VALUES, name="user_role", create_type=False)
    jurisdiction_kind = postgresql.ENUM(
        *JURISDICTION_KIND_VALUES, name="jurisdiction_kind", create_type=False
    )
    user_role.create(op.get_bind())
    jurisdiction_kind.create(op.get_bind())

    # --- tenants -------------------------------------------------------------
    op.create_table(
        "tenants",
        _uuid_pk(),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("default_locale", sa.String(10), server_default="en", nullable=False),
        sa.Column(
            "supported_locales",
            postgresql.ARRAY(sa.String(10)),
            server_default=sa.text("'{en,hi}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "settings", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        *_timestamps(),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$'", name="ck_tenants_slug_format"
        ),
    )

    # --- users ---------------------------------------------------------------
    op.create_table(
        "users",
        _uuid_pk(),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT", name="fk_users_tenant_id_tenants"),
            nullable=True,
        ),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("locale", sa.String(10), server_default="en", nullable=False),
        sa.Column(
            "preferences", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("mfa_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("mfa_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("mfa_last_used_step", sa.BigInteger(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "tenant_id",
            "phone",
            name="uq_users_tenant_id_phone",
            postgresql_nulls_not_distinct=True,
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_users_tenant_id_id"),
        sa.CheckConstraint(r"phone ~ '^\+[1-9][0-9]{6,14}$'", name="ck_users_phone_e164"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index(
        "uq_users_tenant_id_email",
        "users",
        ["tenant_id", sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )

    # --- departments ---------------------------------------------------------
    op.create_table(
        "departments",
        _uuid_pk(),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(
                "tenants.id", ondelete="RESTRICT", name="fk_departments_tenant_id_tenants"
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "code", name="uq_departments_tenant_id_code"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_departments_tenant_id_id"),
        sa.CheckConstraint("code ~ '^[A-Z][A-Z0-9_]{1,31}$'", name="ck_departments_code_format"),
    )

    # --- jurisdictions -------------------------------------------------------
    op.create_table(
        "jurisdictions",
        _uuid_pk(),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(
                "tenants.id", ondelete="RESTRICT", name="fk_jurisdictions_tenant_id_tenants"
            ),
            nullable=False,
        ),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("kind", jurisdiction_kind, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.Geometry("MULTIPOLYGON", srid=4326, spatial_index=False),
            nullable=True,
        ),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "code", name="uq_jurisdictions_tenant_id_code"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_jurisdictions_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["jurisdictions.tenant_id", "jurisdictions.id"],
            ondelete="RESTRICT",
            name="fk_jurisdictions_tenant_parent",
        ),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name="ck_jurisdictions_not_own_parent"
        ),
        sa.CheckConstraint("geom IS NULL OR ST_IsValid(geom)", name="ck_jurisdictions_geom_valid"),
    )
    op.create_index(
        "ix_jurisdictions_tenant_id_parent_id", "jurisdictions", ["tenant_id", "parent_id"]
    )
    op.create_index("ix_jurisdictions_geom", "jurisdictions", ["geom"], postgresql_using="gist")

    # --- user_roles ----------------------------------------------------------
    op.create_table(
        "user_roles",
        _uuid_pk(),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(
                "tenants.id", ondelete="RESTRICT", name="fk_user_roles_tenant_id_tenants"
            ),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_user_roles_user_id_users"),
            nullable=False,
        ),
        sa.Column("role", user_role, nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("jurisdiction_id", sa.Uuid(), nullable=True),
        sa.Column(
            "granted_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_user_roles_granted_by_users"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "user_id",
            "role",
            "department_id",
            "jurisdiction_id",
            name="uq_user_roles_user_id_role_department_id_jurisdiction_id",
            postgresql_nulls_not_distinct=True,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
            name="fk_user_roles_tenant_user",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            ondelete="RESTRICT",
            name="fk_user_roles_tenant_department",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "jurisdiction_id"],
            ["jurisdictions.tenant_id", "jurisdictions.id"],
            ondelete="RESTRICT",
            name="fk_user_roles_tenant_jurisdiction",
        ),
        sa.CheckConstraint(
            "(role = 'platform_admin') = (tenant_id IS NULL)",
            name="ck_user_roles_platform_admin_has_no_tenant",
        ),
    )
    op.create_index("ix_user_roles_tenant_id", "user_roles", ["tenant_id"])
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])

    # --- otp_challenges ------------------------------------------------------
    op.create_table(
        "otp_challenges",
        _uuid_pk(),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(
                "tenants.id", ondelete="CASCADE", name="fk_otp_challenges_tenant_id_tenants"
            ),
            nullable=True,
        ),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_otp_challenges_user_id_users"),
            nullable=True,
        ),
        sa.Column("mfa_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("mfa_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(400), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_otp_challenges_tenant_phone", "otp_challenges", ["tenant_id", "phone", "created_at"]
    )

    # --- auth_sessions -------------------------------------------------------
    op.create_table(
        "auth_sessions",
        _uuid_pk(),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(
                "tenants.id", ondelete="CASCADE", name="fk_auth_sessions_tenant_id_tenants"
            ),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_auth_sessions_user_id_users"),
            nullable=False,
        ),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column(
            "parent_id",
            sa.Uuid(),
            sa.ForeignKey(
                "auth_sessions.id",
                ondelete="SET NULL",
                name="fk_auth_sessions_parent_id_auth_sessions",
            ),
            nullable=True,
        ),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False),
        sa.Column("mfa_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(40), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(400), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("refresh_token_hash", name="uq_auth_sessions_refresh_token_hash"),
    )
    op.create_index("ix_auth_sessions_tenant_id", "auth_sessions", ["tenant_id"])
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_family_id", "auth_sessions", ["family_id"])

    # --- idempotency_keys ----------------------------------------------------
    op.create_table(
        "idempotency_keys",
        _uuid_pk(),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(
                "tenants.id", ondelete="CASCADE", name="fk_idempotency_keys_tenant_id_tenants"
            ),
            nullable=True,
        ),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="CASCADE", name="fk_idempotency_keys_actor_id_users"
            ),
            nullable=True,
        ),
        sa.Column("scope", sa.String(200), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_id",
            "scope",
            "key",
            name="uq_idempotency_keys_tenant_id_actor_id_scope_key",
            postgresql_nulls_not_distinct=True,
        ),
    )

    # --- audit_events (append-only) ------------------------------------------
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(
                "tenants.id", ondelete="RESTRICT", name="fk_audit_events_tenant_id_tenants"
            ),
            nullable=True,
        ),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(100), nullable=True),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(400), nullable=True),
    )
    op.create_index("ix_audit_events_tenant_occurred", "audit_events", ["tenant_id", "occurred_at"])
    op.create_index(
        "ix_audit_events_tenant_entity", "audit_events", ["tenant_id", "entity_type", "entity_id"]
    )
    op.create_index("ix_audit_events_tenant_actor", "audit_events", ["tenant_id", "actor_id"])

    op.execute(
        """
        CREATE FUNCTION audit_events_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only: % is not allowed', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_reject_change()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_no_truncate
        BEFORE TRUNCATE ON audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION audit_events_reject_change()
        """
    )

    # --- privileges for the application role ---------------------------------
    # The role name is validated by _app_role() and the table names are
    # constants, so building this statement with an f-string is safe.
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
    for table in (
        "audit_events",
        "idempotency_keys",
        "auth_sessions",
        "otp_challenges",
        "user_roles",
        "jurisdictions",
        "departments",
        "users",
        "tenants",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION IF EXISTS audit_events_reject_change()")
    op.execute("DROP TYPE IF EXISTS jurisdiction_kind")
    op.execute("DROP TYPE IF EXISTS user_role")
