"""Reporting loop: categories, media, reports, civic issues, timeline,
workflow transitions and reference counters.

Revision ID: 0002
Revises: 0001
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

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of the vocabularies at the time of this migration. Later
# changes belong in later migrations, not in edits to these lists.
ISSUE_STATUSES = (
    "reported",
    "under_review",
    "verified",
    "assigned",
    "in_progress",
    "pending_verification",
    "resolved",
    "rejected",
    "closed",
    "reopened",
)
ROLES = (
    "citizen",
    "community_contributor",
    "operator",
    "supervisor",
    "field_worker",
    "municipal_admin",
    "platform_admin",
)

# Issue timeline rows are history: insert-only, like audit_events. Reports
# and categories are never deleted either (withdrawn / deactivated instead).
APP_GRANTS = {
    "categories": "SELECT, INSERT, UPDATE",
    "status_transitions": "SELECT, INSERT, UPDATE, DELETE",
    "reference_counters": "SELECT, INSERT, UPDATE",
    "media_assets": "SELECT, INSERT, UPDATE, DELETE",
    "civic_issues": "SELECT, INSERT, UPDATE",
    "reports": "SELECT, INSERT, UPDATE",
    "issue_events": "SELECT, INSERT",
}
TENANT_SCOPED_TABLES = tuple(APP_GRANTS)
TENANT_PREDICATE = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    " OR current_setting('app.bypass_rls', true) = 'on'"
)

STAFF = ("operator", "supervisor", "municipal_admin")
SENIOR = ("supervisor", "municipal_admin")
# (from, to, roles, requires_reason, system_only): the Phase 1 defaults from
# docs/api/phase-1-contract.md §7, backfilled for tenants that already exist.
DEFAULT_TRANSITIONS = (
    ("reported", "under_review", STAFF, False, False),
    ("reported", "verified", STAFF, False, False),
    ("under_review", "verified", STAFF, False, False),
    ("reported", "rejected", STAFF, True, False),
    ("under_review", "rejected", STAFF, True, False),
    ("rejected", "under_review", SENIOR, True, False),
    ("verified", "assigned", (), False, True),
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


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _point() -> geoalchemy2.Geometry:
    return geoalchemy2.Geometry("POINT", srid=4326, spatial_index=False)


def upgrade() -> None:
    statuses = _in(ISSUE_STATUSES)

    # --- categories ----------------------------------------------------------
    op.create_table(
        "categories",
        _uuid_pk(),
        _tenant("categories"),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name_i18n", postgresql.JSONB(), nullable=False),
        sa.Column(
            "description_i18n",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("icon", sa.String(64), nullable=False),
        sa.Column("min_photos", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("max_photos", sa.SmallInteger(), server_default=sa.text("5"), nullable=False),
        sa.Column(
            "fields", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("default_department_id", sa.Uuid(), nullable=True),
        sa.Column("dedup_radius_m", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column("dedup_window_days", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "code", name="uq_categories_tenant_id_code"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_categories_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["categories.tenant_id", "categories.id"],
            ondelete="RESTRICT",
            name="fk_categories_tenant_parent",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "default_department_id"],
            ["departments.tenant_id", "departments.id"],
            ondelete="RESTRICT",
            name="fk_categories_tenant_department",
        ),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,49}$'", name="ck_categories_code_format"),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name="ck_categories_not_own_parent"
        ),
        sa.CheckConstraint(
            "min_photos >= 0 AND max_photos >= min_photos AND max_photos <= 10",
            name="ck_categories_evidence_range",
        ),
        sa.CheckConstraint(
            "dedup_radius_m > 0 AND dedup_window_days > 0", name="ck_categories_dedup_positive"
        ),
        sa.CheckConstraint("jsonb_typeof(fields) = 'array'", name="ck_categories_fields_is_array"),
    )
    op.create_index("ix_categories_tenant_id_sort_order", "categories", ["tenant_id", "sort_order"])

    # --- status_transitions --------------------------------------------------
    op.create_table(
        "status_transitions",
        _uuid_pk(),
        _tenant("status_transitions"),
        sa.Column("from_status", sa.String(32), nullable=False),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column(
            "allowed_roles",
            postgresql.ARRAY(sa.String(32)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("requires_reason", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("system_only", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "tenant_id",
            "from_status",
            "to_status",
            name="uq_status_transitions_tenant_id_from_status_to_status",
        ),
        sa.CheckConstraint(
            f"from_status IN ({statuses})", name="ck_status_transitions_from_status_values"
        ),
        sa.CheckConstraint(
            f"to_status IN ({statuses})", name="ck_status_transitions_to_status_values"
        ),
        sa.CheckConstraint("from_status <> to_status", name="ck_status_transitions_not_a_loop"),
        sa.CheckConstraint(
            f"allowed_roles <@ ARRAY[{_in(ROLES)}]::varchar[]",
            name="ck_status_transitions_allowed_roles_values",
        ),
        sa.CheckConstraint(
            "NOT system_only OR cardinality(allowed_roles) = 0",
            name="ck_status_transitions_system_only_has_no_roles",
        ),
    )

    # --- reference_counters --------------------------------------------------
    op.create_table(
        "reference_counters",
        _tenant("reference_counters"),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("last_value", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "kind", "year", name="pk_reference_counters"),
        sa.CheckConstraint("kind IN ('report', 'issue')", name="ck_reference_counters_kind_values"),
        sa.CheckConstraint("last_value >= 0", name="ck_reference_counters_last_value_positive"),
    )

    # --- media_assets ----------------------------------------------------------
    op.create_table(
        "media_assets",
        _uuid_pk(),
        _tenant("media_assets"),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("declared_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(300), nullable=False),
        sa.Column("display_key", sa.String(300), nullable=True),
        sa.Column("thumb_key", sa.String(300), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exif", postgresql.JSONB(), nullable=True),
        sa.Column("failure_reason", sa.String(200), nullable=True),
        sa.Column("report_id", sa.Uuid(), nullable=True),
        sa.Column("position", sa.SmallInteger(), nullable=True),
        sa.Column("upload_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "id", name="uq_media_assets_tenant_id_id"),
        sa.UniqueConstraint("storage_key", name="uq_media_assets_storage_key"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
            name="fk_media_assets_tenant_owner",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')",
            name="ck_media_assets_status_values",
        ),
        sa.CheckConstraint("purpose IN ('report_evidence')", name="ck_media_assets_purpose_values"),
        sa.CheckConstraint(
            "content_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="ck_media_assets_content_type_values",
        ),
        sa.CheckConstraint(
            "declared_size_bytes > 0", name="ck_media_assets_declared_size_positive"
        ),
        sa.CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'", name="ck_media_assets_checksum_format"
        ),
        sa.CheckConstraint(
            "report_id IS NULL OR status <> 'pending'", name="ck_media_assets_attached_is_verified"
        ),
    )
    op.create_index(
        "ix_media_assets_tenant_owner_status", "media_assets", ["tenant_id", "owner_id", "status"]
    )
    op.create_index("ix_media_assets_report_id", "media_assets", ["report_id"])
    op.create_index("ix_media_assets_status_created_at", "media_assets", ["status", "created_at"])

    # --- civic_issues ----------------------------------------------------------
    op.create_table(
        "civic_issues",
        _uuid_pk(),
        _tenant("civic_issues"),
        sa.Column("reference", sa.String(20), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("location", _point(), nullable=False),
        sa.Column("address_text", sa.String(500), nullable=True),
        sa.Column("ward_id", sa.Uuid(), nullable=True),
        sa.Column("report_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "unique_reporter_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("severity", sa.String(16), nullable=True),
        sa.Column("priority", sa.String(16), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("cover_media_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "search_document",
            postgresql.TSVECTOR(),
            server_default=sa.text("''::tsvector"),
            nullable=False,
        ),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "reference", name="uq_civic_issues_tenant_id_reference"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_civic_issues_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            ondelete="RESTRICT",
            name="fk_civic_issues_tenant_category",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ward_id"],
            ["jurisdictions.tenant_id", "jurisdictions.id"],
            ondelete="RESTRICT",
            name="fk_civic_issues_tenant_ward",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "cover_media_id"],
            ["media_assets.tenant_id", "media_assets.id"],
            ondelete="RESTRICT",
            name="fk_civic_issues_tenant_cover_media",
        ),
        sa.CheckConstraint(f"status IN ({statuses})", name="ck_civic_issues_status_values"),
        sa.CheckConstraint(
            "report_count >= 0 AND unique_reporter_count BETWEEN 0 AND report_count",
            name="ck_civic_issues_counts_consistent",
        ),
        sa.CheckConstraint("version >= 1", name="ck_civic_issues_version_positive"),
    )
    op.create_index(
        "ix_civic_issues_location", "civic_issues", ["location"], postgresql_using="gist"
    )
    op.create_index(
        "ix_civic_issues_search_document",
        "civic_issues",
        ["search_document"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_civic_issues_tenant_status_created",
        "civic_issues",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index("ix_civic_issues_tenant_created", "civic_issues", ["tenant_id", "created_at"])
    op.create_index("ix_civic_issues_tenant_updated", "civic_issues", ["tenant_id", "updated_at"])
    op.create_index("ix_civic_issues_tenant_category", "civic_issues", ["tenant_id", "category_id"])
    op.create_index("ix_civic_issues_tenant_ward", "civic_issues", ["tenant_id", "ward_id"])
    op.create_index(
        "ix_civic_issues_tenant_report_count", "civic_issues", ["tenant_id", "report_count"]
    )

    # --- reports -----------------------------------------------------------------
    op.create_table(
        "reports",
        _uuid_pk(),
        _tenant("reports"),
        sa.Column("reference", sa.String(20), nullable=False),
        sa.Column("reporter_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("issue_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "details", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("location", _point(), nullable=False),
        sa.Column("location_accuracy_m", sa.Float(), nullable=True),
        sa.Column("location_source", sa.String(16), nullable=False),
        sa.Column("address_text", sa.String(500), nullable=True),
        sa.Column("ward_id", sa.Uuid(), nullable=True),
        sa.Column("client_created_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "reference", name="uq_reports_tenant_id_reference"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_reports_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reporter_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
            name="fk_reports_tenant_reporter",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            ondelete="RESTRICT",
            name="fk_reports_tenant_category",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "issue_id"],
            ["civic_issues.tenant_id", "civic_issues.id"],
            ondelete="RESTRICT",
            name="fk_reports_tenant_issue",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ward_id"],
            ["jurisdictions.tenant_id", "jurisdictions.id"],
            ondelete="RESTRICT",
            name="fk_reports_tenant_ward",
        ),
        sa.CheckConstraint("status IN ('accepted', 'withdrawn')", name="ck_reports_status_values"),
        sa.CheckConstraint(
            "location_source IN ('gps', 'pin', 'manual')", name="ck_reports_location_source_values"
        ),
        sa.CheckConstraint(
            "char_length(description) <= 2000", name="ck_reports_description_length"
        ),
        sa.CheckConstraint(
            "location_accuracy_m IS NULL OR location_accuracy_m >= 0",
            name="ck_reports_accuracy_positive",
        ),
        sa.CheckConstraint("jsonb_typeof(details) = 'object'", name="ck_reports_details_is_object"),
    )
    op.create_index(
        "ix_reports_tenant_reporter_created", "reports", ["tenant_id", "reporter_id", "created_at"]
    )
    op.create_index("ix_reports_issue_id", "reports", ["issue_id"])
    op.create_index("ix_reports_location", "reports", ["location"], postgresql_using="gist")

    # media_assets -> reports closes the media/report/issue cycle.
    op.create_foreign_key(
        "fk_media_assets_tenant_report",
        "media_assets",
        "reports",
        ["tenant_id", "report_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )

    # --- issue_events (append-only) --------------------------------------------
    op.create_table(
        "issue_events",
        _uuid_pk(),
        _tenant("issue_events"),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("public_note", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_issue_events_actor_id_users"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "issue_id"],
            ["civic_issues.tenant_id", "civic_issues.id"],
            ondelete="RESTRICT",
            name="fk_issue_events_tenant_issue",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "report_id"],
            ["reports.tenant_id", "reports.id"],
            ondelete="RESTRICT",
            name="fk_issue_events_tenant_report",
        ),
        sa.CheckConstraint(
            "type IN ('created', 'status_changed', 'note')", name="ck_issue_events_type_values"
        ),
        sa.CheckConstraint(
            "visibility IN ('public', 'internal')", name="ck_issue_events_visibility_values"
        ),
        sa.CheckConstraint(
            "type <> 'status_changed' OR to_status IS NOT NULL",
            name="ck_issue_events_status_change_has_target",
        ),
    )
    op.create_index("ix_issue_events_issue_created", "issue_events", ["issue_id", "created_at"])

    # --- full-text search document ---------------------------------------------
    # The `simple` configuration lower-cases and splits words without
    # stemming, which is what makes Hindi (and mixed-script) text searchable.
    # Triggers run as the invoking role, so RLS applies inside them too.
    op.execute(
        """
        CREATE FUNCTION civic_issue_search_document(p_issue_id uuid, p_reference text,
                                                    p_address text)
        RETURNS tsvector LANGUAGE sql STABLE AS $$
            SELECT to_tsvector('simple', concat_ws(' ', p_reference, p_address,
                (SELECT string_agg(concat_ws(' ', r.reference, r.address_text, r.description),
                                   ' ' ORDER BY r.created_at)
                   FROM reports r WHERE r.issue_id = p_issue_id)))
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION civic_issues_set_search_document() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.search_document := civic_issue_search_document(
                NEW.id, NEW.reference, NEW.address_text);
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER civic_issues_search_document
        BEFORE INSERT OR UPDATE OF reference, address_text ON civic_issues
        FOR EACH ROW EXECUTE FUNCTION civic_issues_set_search_document()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reports_refresh_issue_search() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND OLD.issue_id IS DISTINCT FROM NEW.issue_id
               AND OLD.issue_id IS NOT NULL THEN
                UPDATE civic_issues
                   SET search_document = civic_issue_search_document(id, reference, address_text)
                 WHERE id = OLD.issue_id;
            END IF;
            IF NEW.issue_id IS NOT NULL THEN
                UPDATE civic_issues
                   SET search_document = civic_issue_search_document(id, reference, address_text)
                 WHERE id = NEW.issue_id;
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER reports_refresh_issue_search
        AFTER INSERT OR UPDATE OF issue_id, reference, description, address_text ON reports
        FOR EACH ROW EXECUTE FUNCTION reports_refresh_issue_search()
        """
    )

    # --- row-level security (same policy as every tenant table) ----------------
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

    # --- default workflow for tenants that already exist ----------------------
    # New tenants get the same rows from the platform tenant endpoint.
    rows = ",\n".join(
        f"('{src}', '{dst}', ARRAY[{_in(roles)}]::varchar[], {str(reason).lower()}, "
        f"{str(system).lower()})"
        for src, dst, roles, reason, system in DEFAULT_TRANSITIONS
    )
    op.execute(
        f"""
        INSERT INTO status_transitions
            (tenant_id, from_status, to_status, allowed_roles, requires_reason, system_only)
        SELECT t.id, d.from_status, d.to_status, d.allowed_roles, d.requires_reason,
               d.system_only
        FROM tenants t
        CROSS JOIN (VALUES {rows})
            AS d(from_status, to_status, allowed_roles, requires_reason, system_only)
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS reports_refresh_issue_search ON reports")
    op.execute("DROP TRIGGER IF EXISTS civic_issues_search_document ON civic_issues")
    op.drop_constraint("fk_media_assets_tenant_report", "media_assets", type_="foreignkey")
    for table in (
        "issue_events",
        "reports",
        "civic_issues",
        "media_assets",
        "reference_counters",
        "status_transitions",
        "categories",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION IF EXISTS reports_refresh_issue_search()")
    op.execute("DROP FUNCTION IF EXISTS civic_issues_set_search_document()")
    op.execute("DROP FUNCTION IF EXISTS civic_issue_search_document(uuid, text, text)")
