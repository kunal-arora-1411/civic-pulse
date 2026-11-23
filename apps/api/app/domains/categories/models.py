"""Issue categories, configured per tenant (PRD FR-019, FR-023, FR-079)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

CATEGORY_CODE_PATTERN = r"^[a-z][a-z0-9_]{1,49}$"
MAX_PHOTOS_PER_REPORT = 10


class Category(TimestampMixin, Base):
    """A kind of civic issue, with the evidence and extra fields it asks for.

    `fields` is a JSON array of field definitions (validated by the API, see
    app/domains/categories/schemas.py); reports store their answers in
    `reports.details`. Categories are deactivated, never deleted, because
    reports keep pointing at them.
    """

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["categories.tenant_id", "categories.id"],
            ondelete="RESTRICT",
            name="fk_categories_tenant_parent",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "default_department_id"],
            ["departments.tenant_id", "departments.id"],
            ondelete="RESTRICT",
            name="fk_categories_tenant_department",
        ),
        CheckConstraint(f"code ~ '{CATEGORY_CODE_PATTERN}'", name="code_format"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
        CheckConstraint(
            "min_photos >= 0 AND max_photos >= min_photos "
            f"AND max_photos <= {MAX_PHOTOS_PER_REPORT}",
            name="evidence_range",
        ),
        CheckConstraint("dedup_radius_m > 0 AND dedup_window_days > 0", name="dedup_positive"),
        CheckConstraint("jsonb_typeof(fields) = 'array'", name="fields_is_array"),
        Index("ix_categories_tenant_id_sort_order", "tenant_id", "sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    code: Mapped[str] = mapped_column(String(50))
    parent_id: Mapped[uuid.UUID | None] = mapped_column()
    name_i18n: Mapped[dict[str, str]] = mapped_column(JSONB)
    description_i18n: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    icon: Mapped[str] = mapped_column(String(64), default="circle-alert")
    min_photos: Mapped[int] = mapped_column(SmallInteger, default=1, server_default=text("1"))
    max_photos: Mapped[int] = mapped_column(SmallInteger, default=5, server_default=text("5"))
    fields: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    default_department_id: Mapped[uuid.UUID | None] = mapped_column()
    # Stored now, used by duplicate matching from Phase 2.
    dedup_radius_m: Mapped[int] = mapped_column(Integer, default=30, server_default=text("30"))
    dedup_window_days: Mapped[int] = mapped_column(Integer, default=30, server_default=text("30"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
