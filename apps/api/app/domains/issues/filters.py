"""Query parameters shared by the issue list and the map (GeoJSON) endpoint."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, Query

from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.domains.priority.rules import PriorityBand, SeverityLevel
from app.domains.workflow.statuses import IssueStatus

BBox = tuple[float, float, float, float]
BBOX_HELP = "`minLng,minLat,maxLng,maxLat`"


@dataclass(frozen=True, slots=True)
class IssueFilters:
    statuses: list[IssueStatus]
    category_ids: list[uuid.UUID]
    ward_ids: list[uuid.UUID]
    created_from: datetime | None  # inclusive
    created_before: datetime | None  # exclusive
    q: str | None
    bbox: BBox | None = None
    severities: list[SeverityLevel] = field(default_factory=list)
    priority_bands: list[PriorityBand] = field(default_factory=list)


def _invalid(param: str, msg: str) -> ValidationFailed:
    return ValidationFailed(
        "The request is invalid.",
        details={"errors": [{"loc": ["query", param], "msg": msg, "type": "value_error"}]},
    )


def parse_bbox(value: str) -> BBox:
    try:
        min_lng, min_lat, max_lng, max_lat = (float(p) for p in value.split(","))
    except ValueError:
        raise _invalid("bbox", "Expected minLng,minLat,maxLng,maxLat.") from None
    if not (-180 <= min_lng < max_lng <= 180 and -90 <= min_lat < max_lat <= 90):
        raise _invalid("bbox", "Coordinates out of range, or a minimum is not below its maximum.")
    return min_lng, min_lat, max_lng, max_lat


def _local_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=ZoneInfo(get_settings().local_timezone))


def _common(
    status: Annotated[
        list[IssueStatus] | None, Query(description="Repeatable; matches any.")
    ] = None,
    category_id: Annotated[
        list[uuid.UUID] | None, Query(description="Repeatable; matches any.")
    ] = None,
    ward_id: Annotated[
        list[uuid.UUID] | None, Query(description="Repeatable; matches any.")
    ] = None,
    date_from: Annotated[
        date | None,
        Query(alias="from", description="Created on or after this day (Asia/Kolkata)."),
    ] = None,
    date_to: Annotated[
        date | None,
        Query(alias="to", description="Created on or before this day (Asia/Kolkata)."),
    ] = None,
    q: Annotated[
        str | None,
        Query(
            max_length=200,
            description="Searches issue and report references, addresses and report "
            "descriptions. Words match by prefix; Hindi works too.",
        ),
    ] = None,
    severity: Annotated[
        list[SeverityLevel] | None, Query(description="Repeatable; matches any.")
    ] = None,
    priority_band: Annotated[
        list[PriorityBand] | None,
        Query(description="The effective band (an override counts). Repeatable."),
    ] = None,
) -> IssueFilters:
    if date_from and date_to and date_from > date_to:
        raise _invalid("from", "`from` is after `to`.")
    return IssueFilters(
        statuses=status or [],
        category_ids=category_id or [],
        ward_ids=ward_id or [],
        created_from=_local_midnight(date_from) if date_from else None,
        created_before=_local_midnight(date_to + timedelta(days=1)) if date_to else None,
        q=(q.strip() or None) if q else None,
        severities=severity or [],
        priority_bands=priority_band or [],
    )


def issue_filters(
    common: Annotated[IssueFilters, Depends(_common)],
    bbox: Annotated[str | None, Query(description=BBOX_HELP)] = None,
) -> IssueFilters:
    return replace(common, bbox=parse_bbox(bbox) if bbox else None)


def map_filters(
    common: Annotated[IssueFilters, Depends(_common)],
    bbox: Annotated[str, Query(description=f"Required: {BBOX_HELP}.")],
) -> IssueFilters:
    return replace(common, bbox=parse_bbox(bbox))


IssueFiltersDep = Annotated[IssueFilters, Depends(issue_filters)]
MapFiltersDep = Annotated[IssueFilters, Depends(map_filters)]
