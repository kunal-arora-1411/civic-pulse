"""Service announcements an administrator publishes (FR-087)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.domains.workflow.statuses import sql_in


class AnnouncementKind(StrEnum):
    PLANNED_WORKS = "planned_works"
    OUTAGE = "outage"
    ADVISORY = "advisory"


class Announcement(TimestampMixin, Base):
    """A notice for one ward (or the whole city when `ward_id` is null),
    optionally about one category, shown publicly between `starts_at` and
    `ends_at` unless withdrawn."""

    __tablename__ = "announcements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "ward_id"],
            ["jurisdictions.tenant_id", "jurisdictions.id"],
            ondelete="RESTRICT",
            name="fk_announcements_tenant_ward",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            ondelete="RESTRICT",
            name="fk_announcements_tenant_category",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
            name="fk_announcements_tenant_created_by",
        ),
        CheckConstraint(f"kind IN ({sql_in(AnnouncementKind)})", name="kind_values"),
        CheckConstraint("ends_at > starts_at", name="period"),
        Index("ix_announcements_tenant_ends_at", "tenant_id", "ends_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    ward_id: Mapped[uuid.UUID | None] = mapped_column()
    category_id: Mapped[uuid.UUID | None] = mapped_column()
    kind: Mapped[str] = mapped_column(String(24))
    title_i18n: Mapped[dict[str, str]] = mapped_column(JSONB)
    body_i18n: Mapped[dict[str, str]] = mapped_column(JSONB)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column()
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
