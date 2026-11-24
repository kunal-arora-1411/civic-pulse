"""Distance filters in metres that can still use the geometry indexes.

Points are stored as SRID 4326 geometry. An exact metre distance needs the
geography type, but a geography comparison can't use the GiST index on the
geometry column. So each filter is a cheap, index-friendly box test in
degrees (generous enough to contain the circle at that latitude) followed
by the exact geography test on whatever survives it.
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import ColumnElement, and_, func

METERS_PER_DEGREE = 111_320.0


def degree_margin(meters: float, lat: float) -> float:
    """A distance in degrees that covers `meters` in every direction at `lat`."""
    shrink = max(math.cos(math.radians(min(abs(lat), 85.0))), 0.05)
    return meters / (METERS_PER_DEGREE * shrink) * 1.01


def within_meters(a: Any, b: Any, meters: float, *, lat: float) -> ColumnElement[bool]:
    return and_(
        func.ST_DWithin(a, b, degree_margin(meters, lat)),
        func.ST_DWithin(func.geography(a), func.geography(b), meters),
    )


def distance_meters(a: Any, b: Any) -> ColumnElement[float]:
    return func.ST_Distance(func.geography(a), func.geography(b))
