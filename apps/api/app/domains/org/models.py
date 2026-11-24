"""Departments and jurisdictions: how a municipality is organised."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
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


class TeamRole(StrEnum):
    LEAD = "lead"
    MEMBER = "member"


class Team(TimestampMixin, Base):
    """A crew inside a department that takes work orders (FR-061).

    Its service area is a set of jurisdictions (a team covers a ward when one
    of them is the ward or an ancestor of it), and it handles a set of
    categories. `schedule` is `{timezone, days: [{weekday, start, end}]}`,
    read by SLA in Phase 4.
    """

    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "department_id", "name"),
        ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            ondelete="RESTRICT",
            name="fk_teams_tenant_department",
        ),
        CheckConstraint(
            "schedule IS NULL OR jsonb_typeof(schedule) = 'object'", name="schedule_is_object"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    department_id: Mapped[uuid.UUID] = mapped_column()
    name: Mapped[str] = mapped_column(String(120))
    schedule: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (
        PrimaryKeyConstraint("team_id", "user_id"),
        ForeignKeyConstraint(
            ["tenant_id", "team_id"],
            ["teams.tenant_id", "teams.id"],
            ondelete="CASCADE",
            name="fk_team_members_tenant_team",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
            name="fk_team_members_tenant_user",
        ),
        CheckConstraint("team_role IN ('lead', 'member')", name="team_role_values"),
        Index("ix_team_members_user_id", "user_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    team_id: Mapped[uuid.UUID] = mapped_column()
    user_id: Mapped[uuid.UUID] = mapped_column()
    team_role: Mapped[str] = mapped_column(String(16), default=TeamRole.MEMBER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TeamJurisdiction(Base):
    __tablename__ = "team_jurisdictions"
    __table_args__ = (
        PrimaryKeyConstraint("team_id", "jurisdiction_id"),
        ForeignKeyConstraint(
            ["tenant_id", "team_id"],
            ["teams.tenant_id", "teams.id"],
            ondelete="CASCADE",
            name="fk_team_jurisdictions_tenant_team",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "jurisdiction_id"],
            ["jurisdictions.tenant_id", "jurisdictions.id"],
            ondelete="RESTRICT",
            name="fk_team_jurisdictions_tenant_jurisdiction",
        ),
        Index("ix_team_jurisdictions_jurisdiction_id", "jurisdiction_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    team_id: Mapped[uuid.UUID] = mapped_column()
    jurisdiction_id: Mapped[uuid.UUID] = mapped_column()


class TeamCategory(Base):
    __tablename__ = "team_categories"
    __table_args__ = (
        PrimaryKeyConstraint("team_id", "category_id"),
        ForeignKeyConstraint(
            ["tenant_id", "team_id"],
            ["teams.tenant_id", "teams.id"],
            ondelete="CASCADE",
            name="fk_team_categories_tenant_team",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            ondelete="RESTRICT",
            name="fk_team_categories_tenant_category",
        ),
        Index("ix_team_categories_category_id", "category_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    team_id: Mapped[uuid.UUID] = mapped_column()
    category_id: Mapped[uuid.UUID] = mapped_column()
