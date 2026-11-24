"""Public resolution tracking, no login: /api/v1/public/{tenant}/...

The tenant comes from the path (its slug), so a URL is a complete cache
key. Responses are cacheable by browsers and CDNs for a short while, and
each client address gets a generous per-minute allowance.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from app.core.db import DbSession
from app.core.errors import NotFound, ServiceUnavailable, error_responses
from app.core.logging import log_fields
from app.core.pagination import PageParamsDep
from app.core.ratelimit import enforce_window
from app.core.redis import get_redis
from app.core.storage import Storage
from app.core.tenancy import set_tenant
from app.domains.public import service
from app.domains.public.schemas import (
    PublicFeatureCollection,
    PublicIssueDetail,
    PublicIssuePage,
    Scorecard,
)
from app.domains.tenants import service as tenants
from app.domains.workflow.statuses import IssueStatus

logger = logging.getLogger(__name__)

PUBLIC_RATE_LIMIT = 300  # requests per client address per minute
CACHE_CONTROL = "public, max-age=30, stale-while-revalidate=120"


async def _public_tenant(
    request: Request,
    response: Response,
    db: DbSession,
    tenant: Annotated[str, Path(max_length=63, description="Tenant slug, e.g. `demo-city`.")],
) -> uuid.UUID:
    client = request.client.host if request.client else "unknown"
    try:
        await enforce_window(get_redis(), f"ratelimit:public:{client}", PUBLIC_RATE_LIMIT, 60)
    except ServiceUnavailable:
        # Read-only public data: an unreachable limiter must not take the
        # tracker down with it.
        logger.warning("public rate limit skipped", extra=log_fields(client=client))
    row = await tenants.get_active_by_slug(db, tenant)
    if row is None:
        raise NotFound("Unknown tenant.")
    await set_tenant(db, row.id)
    response.headers["Cache-Control"] = CACHE_CONTROL
    return row.id


PublicTenant = Annotated[uuid.UUID, Depends(_public_tenant)]
Statuses = Annotated[list[IssueStatus] | None, Query(alias="status")]

router = APIRouter(prefix="/public/{tenant}", tags=["public"])


@router.get(
    "/issues",
    operation_id="public_issues_list",
    response_model=PublicIssuePage,
    responses=error_responses(404, 422, 429),
)
async def list_issues(
    _: PublicTenant,
    db: DbSession,
    storage: Storage,
    page: PageParamsDep,
    status: Statuses = None,
    category_id: uuid.UUID | None = None,
    ward_id: uuid.UUID | None = None,
    sort: Annotated[
        str, Query(description=f"One of {', '.join(f'`{s}`' for s in service.SORTS)}.")
    ] = "-created_at",
) -> PublicIssuePage:
    """Issues with generalised locations, newest first by default."""
    items, total = await service.list_issues(
        db,
        storage,
        page,
        statuses=status,
        category_id=category_id,
        ward_id=ward_id,
        sort=sort,
    )
    return PublicIssuePage(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/issues/geojson",
    operation_id="public_issues_geojson",
    response_model=PublicFeatureCollection,
    responses=error_responses(404, 422, 429),
)
async def issues_geojson(
    _: PublicTenant,
    db: DbSession,
    status: Statuses = None,
    category_id: uuid.UUID | None = None,
    ward_id: uuid.UUID | None = None,
) -> PublicFeatureCollection:
    """Generalised points for the map, `[lng, lat]`, at most 2000."""
    return await service.geojson(db, statuses=status, category_id=category_id, ward_id=ward_id)


@router.get(
    "/issues/{issue_id}",
    operation_id="public_issues_get",
    response_model=PublicIssueDetail,
    responses=error_responses(404, 422, 429),
)
async def get_issue(
    _: PublicTenant, db: DbSession, storage: Storage, issue_id: uuid.UUID
) -> PublicIssueDetail:
    """The public timeline and face-blurred before/after photos."""
    return await service.get_issue(db, storage, issue_id)


@router.get(
    "/scorecard",
    operation_id="public_scorecard",
    response_model=Scorecard,
    responses=error_responses(404, 422, 429),
)
async def scorecard(_: PublicTenant, db: DbSession) -> Scorecard:
    """Per ward: open issues, resolved issues and the median days to resolve."""
    return await service.scorecard(db)
