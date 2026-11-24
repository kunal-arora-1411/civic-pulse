"""AI records: the model registry, image embeddings and classifications.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-24
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 512 is CLIP ViT-B/32's width (and the fake model's). A model with another
# dimension gets a new column or table in a new migration; vectors of one
# model are never compared with another's.
EMBEDDING_DIM = 512

APP_GRANTS = {
    "model_registry": "SELECT, INSERT, UPDATE",
    "media_embeddings": "SELECT, INSERT, DELETE",
    "classifications": "SELECT, INSERT, UPDATE",
}
# model_registry is deliberately absent: it describes deployed software and
# holds no tenant data, so every tenant reads the same rows.
TENANT_SCOPED_TABLES = ("media_embeddings", "classifications")
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


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "model_registry",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("task", sa.String(32), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("version", sa.String(100), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("license", sa.String(200), nullable=True),
        _now("deployed_at"),
        sa.Column("intended_use", sa.Text(), nullable=True),
        sa.Column(
            "metrics", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint(
            "task IN ('embedding', 'classification', 'face_detection')",
            name="ck_model_registry_task_values",
        ),
    )

    op.create_table(
        "media_embeddings",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant("media_embeddings"),
        sa.Column("media_id", sa.Uuid(), nullable=False),
        sa.Column(
            "model_id",
            sa.String(100),
            sa.ForeignKey(
                "model_registry.id",
                ondelete="RESTRICT",
                name="fk_media_embeddings_model_id_model_registry",
            ),
            nullable=False,
        ),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("phash", sa.BigInteger(), nullable=False),
        _now("created_at"),
        sa.UniqueConstraint("media_id", "model_id", name="uq_media_embeddings_media_id_model_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "media_id"],
            ["media_assets.tenant_id", "media_assets.id"],
            ondelete="CASCADE",
            name="fk_media_embeddings_tenant_media",
        ),
    )
    # Cosine distance, matching how similarity is scored. Defaults for m and
    # ef_construction suit a city's worth of photos.
    op.create_index(
        "ix_media_embeddings_embedding_hnsw",
        "media_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "classifications",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant("classifications"),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("media_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("scores", postgresql.JSONB(), nullable=True),
        sa.Column("top_code", sa.String(50), nullable=True),
        sa.Column("top_confidence", sa.Float(), nullable=True),
        sa.Column("error", sa.String(100), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_classifications_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
            name="fk_classifications_tenant_requested_by",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'done', 'failed')", name="ck_classifications_status_values"
        ),
        sa.CheckConstraint(
            "cardinality(media_ids) BETWEEN 1 AND 10", name="ck_classifications_media_count"
        ),
        sa.CheckConstraint(
            "top_confidence IS NULL OR top_confidence BETWEEN 0 AND 1",
            name="ck_classifications_confidence_range",
        ),
    )
    op.create_index(
        "ix_classifications_tenant_status_created",
        "classifications",
        ["tenant_id", "status", "created_at"],
    )

    op.add_column(
        "media_assets", sa.Column("faces_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("media_assets", sa.Column("face_count", sa.SmallInteger(), nullable=True))
    op.add_column("categories", sa.Column("ai_prompts", postgresql.JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_categories_ai_prompts_is_array",
        "categories",
        "ai_prompts IS NULL OR jsonb_typeof(ai_prompts) = 'array'",
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
    op.drop_constraint("ck_categories_ai_prompts_is_array", "categories", type_="check")
    op.drop_column("categories", "ai_prompts")
    op.drop_column("media_assets", "face_count")
    op.drop_column("media_assets", "faces_checked_at")
    for table in ("classifications", "media_embeddings", "model_registry"):
        op.drop_table(table)
