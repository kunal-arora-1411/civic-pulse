from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.pagination import PageParamsDep
from app.core.storage import Storage
from app.domains.issues import service
from app.domains.issues.filters import IssueFiltersDep, MapFiltersDep
from app.domains.issues.schemas import IssueDetail, IssueFeatureCollection, IssuePage
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal

router = APIRouter(prefix="/issues", tags=["issues"])

IssueReader = Annotated[Principal, require(Permission.ISSUE_READ)]


@router.get(
    "",
    operation_id="issues_list",
    response_model=IssuePage,
    responses=error_responses(401, 403, 422),
)
async def list_issues(
    principal: IssueReader,
    db: DbSession,
    storage: Storage,
    page: PageParamsDep,
    filters: IssueFiltersDep,
    sort: Annotated[
        str | None,
        Query(
            description="`-created_at` (default), `created_at`, `-updated_at`, `updated_at`, "
            "`-report_count` or `report_count`."
        ),
    ] = None,
) -> IssuePage:
    """The work queue, limited to the caller's jurisdiction scope."""
    items, total = await service.list_issues(db, storage, principal, page, filters, sort=sort)
    return IssuePage(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/geojson",
    operation_id="issues_geojson",
    response_model=IssueFeatureCollection,
    responses=error_responses(401, 403, 422),
)
async def issues_geojson(
    principal: IssueReader, db: DbSession, filters: MapFiltersDep
) -> IssueFeatureCollection:
    """Issues in `bbox` as GeoJSON points, newest first, for the map. At most
    5000 features; `truncated` says whether more matched."""
    return await service.issues_geojson(db, principal, filters)


@router.get(
    "/{issue_id}",
    operation_id="issues_get",
    response_model=IssueDetail,
    responses=error_responses(401, 403, 404, 422),
)
async def get_issue(
    principal: IssueReader, db: DbSession, storage: Storage, issue_id: uuid.UUID
) -> IssueDetail:
    """Reports, media, the full timeline and the moves the caller may make."""
    return await service.get_detail(db, storage, principal, issue_id)
