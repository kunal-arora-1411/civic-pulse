"""Departments and jurisdictions: how a municipality is organised."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

DEPARTMENT_CODE_PATTERN = r"^[A-Z][A-Z0-9_]{1,31}$"


class JurisdictionKind(StrEnum):
    CITY = "city"
    ZONE = "zone"
    WARD = "ward"
    SERVICE_AREA = "service_area"


class Department(TimestampMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint(f"code ~ '{DEPARTMENT_CODE_PATTERN}'", name="code_format"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class Jurisdiction(TimestampMixin, Base):
    """A city, zone, ward or service area. Jurisdictions form a tree within a
    tenant; the composite parent key keeps every edge inside one tenant."""

    __tablename__ = "jurisdictions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["jurisdictions.tenant_id", "jurisdictions.id"],
            ondelete="RESTRICT",
            name="fk_jurisdictions_tenant_parent",
        ),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
        CheckConstraint("geom IS NULL OR ST_IsValid(geom)", name="geom_valid"),
        Index("ix_jurisdictions_tenant_id_parent_id", "tenant_id", "parent_id"),
        Index("ix_jurisdictions_geom", "geom", postgresql_using="gist"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column()
    kind: Mapped[JurisdictionKind] = mapped_column(
        Enum(
            JurisdictionKind,
            name="jurisdiction_kind",
            values_callable=lambda enum: [member.value for member in enum],
        )
    )
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(32))
    geom: Mapped[Any | None] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326, spatial_index=False)
    )
