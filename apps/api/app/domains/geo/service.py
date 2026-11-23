"""Where a point falls in the municipality, answered from our own boundaries.

All queries run under RLS, so only the current tenant's jurisdictions are
ever considered.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.org.models import Jurisdiction, JurisdictionKind


@dataclass(frozen=True, slots=True)
class Area:
    id: uuid.UUID
    name: str
    code: str


@dataclass(frozen=True, slots=True)
class Placement:
    in_jurisdiction: bool
    ward: Area | None
    zone: Area | None


def point(lng: float, lat: float) -> ColumnElement[Any]:
    return func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)


async def _smallest_covering(
    db: AsyncSession, kind: JurisdictionKind, lng: float, lat: float
) -> Area | None:
    # Smallest first, so overlapping or nested areas resolve to the most
    # specific one; the code breaks ties deterministically. ST_Covers counts
    # boundary points, so a point on a shared ward edge still gets a ward.
    row = (
        await db.execute(
            select(Jurisdiction.id, Jurisdiction.name, Jurisdiction.code)
            .where(
                Jurisdiction.kind == kind,
                Jurisdiction.geom.is_not(None),
                func.ST_Covers(Jurisdiction.geom, point(lng, lat)),
            )
            .order_by(func.ST_Area(Jurisdiction.geom), Jurisdiction.code)
            .limit(1)
        )
    ).first()
    return Area(id=row[0], name=row[1], code=row[2]) if row else None


async def place(db: AsyncSession, lng: float, lat: float) -> Placement:
    """Is the point inside the city, and in which ward and zone?

    The city boundary is the tenant's `city` jurisdiction. A tenant that has
    no city geometry yet counts a point as inside when it falls in a ward.
    """
    ward = await _smallest_covering(db, JurisdictionKind.WARD, lng, lat)
    zone = await _smallest_covering(db, JurisdictionKind.ZONE, lng, lat)
    has_city = await db.scalar(
        select(
            exists().where(
                Jurisdiction.kind == JurisdictionKind.CITY, Jurisdiction.geom.is_not(None)
            )
        )
    )
    if has_city:
        inside = await db.scalar(
            select(
                exists().where(
                    Jurisdiction.kind == JurisdictionKind.CITY,
                    func.ST_Covers(Jurisdiction.geom, point(lng, lat)),
                )
            )
        )
    else:
        inside = ward is not None
    if not inside:
        return Placement(in_jurisdiction=False, ward=None, zone=None)
    return Placement(in_jurisdiction=True, ward=ward, zone=zone)


@dataclass(frozen=True, slots=True)
class MapView:
    center: tuple[float, float]  # (lng, lat)
    zoom: int
    bounds: tuple[float, float, float, float]  # (min_lng, min_lat, max_lng, max_lat)


def _zoom_for(span_degrees: float) -> int:
    # At zoom z one 256 px tile spans 360 / 2^z degrees of longitude; a map
    # a few tiles wide fits a span of about 360 / 2^z.
    if span_degrees <= 0:
        return 15
    return max(3, min(18, math.floor(math.log2(360 / span_degrees))))


async def map_view(db: AsyncSession) -> MapView | None:
    """Initial map position from the city boundary (or, without one, from
    all of the tenant's jurisdictions). None when there is no geometry."""
    for kinds in ([JurisdictionKind.CITY], list(JurisdictionKind)):
        geoms = select(Jurisdiction.geom).where(
            Jurisdiction.kind.in_(kinds), Jurisdiction.geom.is_not(None)
        )
        union = func.ST_Union(geoms.subquery().c.geom)
        row = (
            await db.execute(
                select(
                    func.ST_XMin(func.ST_Envelope(union)),
                    func.ST_YMin(func.ST_Envelope(union)),
                    func.ST_XMax(func.ST_Envelope(union)),
                    func.ST_YMax(func.ST_Envelope(union)),
                    func.ST_X(func.ST_PointOnSurface(union)),
                    func.ST_Y(func.ST_PointOnSurface(union)),
                )
            )
        ).one()
        if row[0] is None:
            continue
        min_lng, min_lat, max_lng, max_lat, center_lng, center_lat = (float(v) for v in row)
        # The centroid looks best but can fall outside an L-shaped city;
        # use it only when it is inside, else a point that surely is.
        centroid = (
            await db.execute(
                select(
                    func.ST_X(func.ST_Centroid(union)),
                    func.ST_Y(func.ST_Centroid(union)),
                    func.ST_Covers(union, func.ST_Centroid(union)),
                )
            )
        ).one()
        if centroid[2]:
            center_lng, center_lat = float(centroid[0]), float(centroid[1])
        span = max(max_lng - min_lng, max_lat - min_lat)
        return MapView(
            center=(round(center_lng, 6), round(center_lat, 6)),
            zoom=_zoom_for(span),
            bounds=(
                round(min_lng, 6),
                round(min_lat, 6),
                round(max_lng, 6),
                round(max_lat, 6),
            ),
        )
    return None
