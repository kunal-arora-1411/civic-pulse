"""Analytics responses. Every figure names the docs/metrics.md entry that
defines it (`metric`), so the dashboard and any export agree."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.domains.categories.schemas import CategoryRef
from app.domains.workflow.statuses import IssueStatus

Interval = Literal["day", "week"]


class Period(BaseModel):
    """IST calendar days, both ends inclusive."""

    start: date
    end: date


class Filters(BaseModel):
    period: Period
    previous: Period
    category_id: uuid.UUID | None
    ward_id: uuid.UUID | None
    status: list[IssueStatus]


class Point(BaseModel):
    bucket: date
    value: float | None


class Kpi(BaseModel):
    metric: str
    """docs/metrics.md entry id, e.g. `resolution_time`."""
    unit: Literal["count", "hours", "ratio"]
    value: float | None
    previous: float | None
    sparkline: list[Point]


class Overview(BaseModel):
    filters: Filters
    kpis: list[Kpi]


class TrendPoint(BaseModel):
    bucket: date
    reports: int
    issues: int
    resolved: int


class Trend(BaseModel):
    metrics: list[str]
    interval: Interval
    filters: Filters
    points: list[TrendPoint]


class StatusCount(BaseModel):
    status: IssueStatus
    count: int


class ByStatus(BaseModel):
    metric: str
    filters: Filters
    total: int
    items: list[StatusCount]


class CategoryRow(BaseModel):
    category: CategoryRef
    total: int
    statuses: list[StatusCount]


class ByCategory(BaseModel):
    metric: str
    filters: Filters
    items: list[CategoryRow]


class WardRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class WardRow(BaseModel):
    ward: WardRef | None
    """None: issues outside every ward."""
    issues: int
    open: int
    resolved: int
    median_resolution_hours: float | None


class ByWard(BaseModel):
    metrics: list[str]
    filters: Filters
    items: list[WardRow]


class Bin(BaseModel):
    lower_hours: float
    upper_hours: float | None
    """None: open-ended last bin."""
    count: int


class ResolutionTimes(BaseModel):
    metric: str
    filters: Filters
    count: int
    mean_hours: float | None
    median_hours: float | None
    p90_hours: float | None
    bins: list[Bin]


class MatchingQuality(BaseModel):
    metrics: list[str]
    filters: Filters
    decided_reports: int
    auto_link_rate: float | None
    review_rate: float | None
    duplicate_rate: float | None
    correction_rate: float | None
    feedback_count: int


class Hotspot(BaseModel):
    cell: str
    """H3 cell index (hex string)."""
    lng: float
    lat: float
    issues: int
    open: int


class Hotspots(BaseModel):
    metric: str
    filters: Filters
    resolution: int
    items: list[Hotspot]


class ActivityCell(BaseModel):
    weekday: int
    """0 = Monday (ISO weekday - 1), IST."""
    hour: int
    count: int


class Activity(BaseModel):
    metric: str
    filters: Filters
    items: list[ActivityCell]
