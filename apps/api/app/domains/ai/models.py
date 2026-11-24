"""What the vision models produced, and which models produced it."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.ai.phash import from_signed64, to_signed64
from app.core.db import Base, TimestampMixin
from app.domains.workflow.statuses import sql_in

# The embedding column's width. A model with another dimension needs a new
# column (or table) and a migration; existing vectors are never resized.
EMBEDDING_DIM = 512


class UnsignedHash64(TypeDecorator[int]):
    """An unsigned 64-bit hash kept in a Postgres ``bigint``.

    Perceptual hashes use all 64 bits, and ``bigint`` is signed, so values
    are stored in two's complement and turned back into unsigned ints on
    the way out. Python code only ever sees the unsigned hash, which is
    what ``perceptual_hash_distance`` and the pHash tests expect. SQL that
    XORs two stored hashes needs no conversion: two's complement keeps the
    bits as they are.
    """

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value: int | None, dialect: object) -> int | None:
        return None if value is None else to_signed64(value)

    def process_result_value(self, value: int | None, dialect: object) -> int | None:
        return None if value is None else from_signed64(value)


class ModelTask(StrEnum):
    EMBEDDING = "embedding"
    CLASSIFICATION = "classification"
    FACE_DETECTION = "face_detection"


class ModelRegistryEntry(TimestampMixin, Base):
    """One deployed model version (PRD §8.2 model governance).

    Global, not per tenant: a row describes software, not anyone's data, so
    the table has no tenant_id and no RLS policy. The active model for a
    task is the one deployed most recently.
    """

    __tablename__ = "model_registry"
    __table_args__ = (CheckConstraint(f"task IN ({sql_in(ModelTask)})", name="task_values"),)

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    task: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(100))
    source: Mapped[str | None] = mapped_column(Text)
    license: Mapped[str | None] = mapped_column(String(200))
    deployed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    intended_use: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )


class MediaEmbedding(Base):
    """An image embedding and perceptual hash for one photo, per model.

    Vectors are written and compared in SQL (casts to `vector`), never
    loaded through the ORM, so the column is deferred.
    """

    __tablename__ = "media_embeddings"
    __table_args__ = (
        UniqueConstraint("media_id", "model_id"),
        ForeignKeyConstraint(
            ["tenant_id", "media_id"],
            ["media_assets.tenant_id", "media_assets.id"],
            ondelete="CASCADE",
            name="fk_media_embeddings_tenant_media",
        ),
        Index(
            "ix_media_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    media_id: Mapped[uuid.UUID] = mapped_column()
    model_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("model_registry.id", ondelete="RESTRICT")
    )
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM), deferred=True)
    # Unsigned 64-bit pHash; signed in the column, see UnsignedHash64.
    phash: Mapped[int] = mapped_column(UnsignedHash64())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClassificationStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class Classification(TimestampMixin, Base):
    """A category suggestion requested while a citizen is reporting (FR-020)."""

    __tablename__ = "classifications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "requested_by"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
            name="fk_classifications_tenant_requested_by",
        ),
        CheckConstraint(f"status IN ({sql_in(ClassificationStatus)})", name="status_values"),
        CheckConstraint("cardinality(media_ids) BETWEEN 1 AND 10", name="media_count"),
        CheckConstraint(
            "top_confidence IS NULL OR top_confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        Index("ix_classifications_tenant_status_created", "tenant_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    requested_by: Mapped[uuid.UUID] = mapped_column()
    media_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid()))
    model_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default=ClassificationStatus.PENDING)
    # [{"code": ..., "confidence": ...}], best first, as the classifier said.
    scores: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB(none_as_null=True))
    top_code: Mapped[str | None] = mapped_column(String(50))
    top_confidence: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(String(100))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
