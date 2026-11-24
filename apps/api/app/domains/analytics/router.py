"""Read-only analytics for staff with `analytics:read` (docs/metrics.md)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.db import DbSession
from app.core.errors import error_responses
from app.domains.analytics import service
from app.domains.analytics.schemas import (
    Activity,
    ByCategory,
    ByStatus,
    ByWard,
    Hotspots,
    Interval,
    MatchingQuality,
    Overview,
    ResolutionTimes,
    Trend,
)
from app.domains.analytics.service import Scope
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.rbac.scope import issue_access
from app.domains.workflow.statuses import IssueStatus

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[require(Permission.ANALYTICS_READ)],
)
RESPONSES = error_responses(401, 403, 422)


async def _scope(
    principal: Annotated[Principal, require(Permission.ANALYTICS_READ)],
    db: DbSession,
    from_: Annotated[
        date | None,
        Query(alias="from", description="First IST day, inclusive (default: 30 days ago)."),
    ] = None,
    to: Annotated[
        date | None, Query(description="Last IST day, inclusive (default today).")
    ] = None,
    category_id: uuid.UUID | None = None,
    ward_id: uuid.UUID | None = None,
    status: Annotated[list[IssueStatus] | None, Query(description="Issue states.")] = None,
) -> Scope:
    access = await issue_access(db, principal, Permission.ANALYTICS_READ)
    return Scope.build(from_, to, category_id, ward_id, status, access)


ScopeDep = Annotated[Scope, Depends(_scope)]


@router.get("/overview", operation_id="analytics_overview", responses=RESPONSES)
async def overview(db: DbSession, scope: ScopeDep) -> Overview:
    """Headline KPIs for the period, the same figures for the period just
    before it, and a sparkline (daily up to 45 days, else weekly)."""
    return await service.overview(db, scope)


@router.get("/trend", operation_id="analytics_trend", responses=RESPONSES)
async def trend(db: DbSession, scope: ScopeDep, interval: Interval = "day") -> Trend:
    """Reports, issues and first resolutions per IST day or ISO week."""
    return await service.trend(db, scope, interval)


@router.get("/by-status", operation_id="analytics_by_status", responses=RESPONSES)
async def by_status(db: DbSession, scope: ScopeDep) -> ByStatus:
    """Issues created in the period, by their current status."""
    return await service.by_status(db, scope)


@router.get("/by-category", operation_id="analytics_by_category", responses=RESPONSES)
async def by_category(db: DbSession, scope: ScopeDep) -> ByCategory:
    """Issues created in the period per category, split by current status."""
    return await service.by_category(db, scope)


@router.get("/by-ward", operation_id="analytics_by_ward", responses=RESPONSES)
async def by_ward(db: DbSession, scope: ScopeDep) -> ByWard:
    """Issues per ward (most first) with open/resolved counts and median
    resolution time."""
    return await service.by_ward(db, scope)


@router.get("/resolution-times", operation_id="analytics_resolution_times", responses=RESPONSES)
async def resolution_times(db: DbSession, scope: ScopeDep) -> ResolutionTimes:
    """Distribution of time to first resolution, in hour bins."""
    return await service.resolution_times(db, scope)


@router.get("/matching-quality", operation_id="analytics_matching_quality", responses=RESPONSES)
async def matching_quality(db: DbSession, scope: ScopeDep) -> MatchingQuality:
    """How duplicate matching performed: auto-link, review, duplicate and
    correction rates."""
    return await service.matching_quality(db, scope)


@router.get("/hotspots", operation_id="analytics_hotspots", responses=RESPONSES)
async def hotspots(
    db: DbSession,
    scope: ScopeDep,
    resolution: Annotated[int, Query(ge=5, le=10, description="H3 resolution.")] = 8,
) -> Hotspots:
    """Issue counts per H3 cell, densest first (at most 400 cells)."""
    return await service.hotspots(db, scope, resolution)


@router.get("/activity", operation_id="analytics_activity", responses=RESPONSES)
async def activity(db: DbSession, scope: ScopeDep) -> Activity:
    """Reports by IST weekday and hour."""
    return await service.activity(db, scope)
