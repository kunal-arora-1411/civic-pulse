"""Places that make a nearby problem more urgent: schools, hospitals and so on."""

from __future__ import annotations

import uuid
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.domains.priority.rules import PlaceKind
from app.domains.workflow.statuses import sql_in


class PlaceOfInterest(TimestampMixin, Base):
    """Used by severity rules (`near_places`) and the priority factor of the
    same name. Seeded synthetically for now; admin editing comes later."""

    __tablename__ = "places_of_interest"
    __table_args__ = (
        CheckConstraint(f"kind IN ({sql_in(PlaceKind)})", name="kind_values"),
        Index("ix_places_of_interest_geom", "geom", postgresql_using="gist"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(200))
    geom: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326, spatial_index=False))
