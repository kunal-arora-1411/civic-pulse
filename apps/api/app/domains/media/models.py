"""Uploaded media and its processed variants."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.domains.workflow.statuses import sql_in


class MediaStatus(StrEnum):
    PENDING = "pending"  # upload URL issued, bytes not verified yet
    PROCESSING = "processing"  # verified; variants being made
    READY = "ready"
    FAILED = "failed"


class MediaPurpose(StrEnum):
    REPORT_EVIDENCE = "report_evidence"


ALLOWED_CONTENT_TYPES = ("image/jpeg", "image/png", "image/webp")


class MediaAsset(TimestampMixin, Base):
    """One uploaded file.

    The original keeps its metadata and is staff-only. `display_key` and
    `thumb_key` point at WebP copies with all metadata removed, which are
    what citizens see. `exif` holds what we chose to keep from the original's
    metadata (capture time, GPS, camera); it is never returned by the API.
    """

    __tablename__ = "media_assets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("storage_key"),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
            name="fk_media_assets_tenant_owner",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "report_id"],
            ["reports.tenant_id", "reports.id"],
            ondelete="RESTRICT",
            name="fk_media_assets_tenant_report",
            use_alter=True,
        ),
        CheckConstraint(f"status IN ({sql_in(MediaStatus)})", name="status_values"),
        CheckConstraint(f"purpose IN ({sql_in(MediaPurpose)})", name="purpose_values"),
        CheckConstraint(
            f"content_type IN ({sql_in(ALLOWED_CONTENT_TYPES)})", name="content_type_values"
        ),
        CheckConstraint("declared_size_bytes > 0", name="declared_size_positive"),
        CheckConstraint("checksum_sha256 ~ '^[0-9a-f]{64}$'", name="checksum_format"),
        # Only verified uploads can be attached to a report.
        CheckConstraint("report_id IS NULL OR status <> 'pending'", name="attached_is_verified"),
        Index("ix_media_assets_tenant_owner_status", "tenant_id", "owner_id", "status"),
        Index("ix_media_assets_report_id", "report_id"),
        Index("ix_media_assets_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    owner_id: Mapped[uuid.UUID] = mapped_column()
    purpose: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default=MediaStatus.PENDING)
    content_type: Mapped[str] = mapped_column(String(64))
    declared_size_bytes: Mapped[int] = mapped_column(BigInteger)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(300))
    display_key: Mapped[str | None] = mapped_column(String(300))
    thumb_key: Mapped[str | None] = mapped_column(String(300))
    # Dimensions as displayed (EXIF orientation applied): the original's until
    # processing finishes, then the display variant's. The ratio is the same.
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exif: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    failure_reason: Mapped[str | None] = mapped_column(String(200))
    report_id: Mapped[uuid.UUID | None] = mapped_column()
    position: Mapped[int | None] = mapped_column(SmallInteger)
    upload_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Face blurring of the display and thumbnail copies (Phase 2): when the
    # copies were checked, and how many faces were blurred. NULL = not yet.
    faces_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    face_count: Mapped[int | None] = mapped_column(SmallInteger)
