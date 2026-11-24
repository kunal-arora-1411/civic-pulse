from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.pagination import PageParamsDep
from app.core.storage import Storage
from app.domains.issues import consolidation, overrides, service
from app.domains.issues.filters import IssueFiltersDep, MapFiltersDep
from app.domains.issues.schemas import (
    CategoryChange,
    IssueDetail,
    IssueFeatureCollection,
    IssuePage,
    MergeRequest,
    PriorityOverride,
    RelatedIssueOut,
    RelatedRequest,
    SeverityOverride,
    SplitRequest,
    SplitResult,
    StatusChange,
)
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal

router = APIRouter(prefix="/issues", tags=["issues"])

IssueReader = Annotated[Principal, require(Permission.ISSUE_READ)]
IssueMerger = Annotated[Principal, require(Permission.ISSUE_READ, Permission.ISSUE_MERGE)]
IssueEditor = Annotated[Principal, require(Permission.ISSUE_READ, Permission.ISSUE_UPDATE)]
PrioritySetter = Annotated[Principal, require(Permission.ISSUE_READ, Permission.ISSUE_SET_PRIORITY)]


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
            description="`-priority` (default: effective band, then score), `priority`, "
            "`-created_at`, `created_at`, `-updated_at`, `updated_at`, `-report_count` or "
            "`report_count`."
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


@router.patch(
    "/{issue_id}/status",
    operation_id="issues_change_status",
    response_model=IssueDetail,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def change_status(
    principal: IssueReader,
    db: DbSession,
    storage: Storage,
    issue_id: uuid.UUID,
    body: StatusChange,
) -> IssueDetail:
    """Move the issue to `to_status` if the tenant's workflow lets the
    caller do so here. Send the `version` you last saw: a stale one is
    `409 version_conflict` (current version in `details.version`). A move
    the caller may not make is `422 invalid_transition`, listing the moves
    they may make. Returns the updated issue."""
    await service.change_status(db, principal, issue_id, body)
    return await service.get_detail(db, storage, principal, issue_id)


@router.post(
    "/{issue_id}/merge",
    operation_id="issues_merge",
    response_model=IssueDetail,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def merge_issues(
    principal: IssueMerger, db: DbSession, storage: Storage, issue_id: uuid.UUID, body: MergeRequest
) -> IssueDetail:
    """Merge `source_issue_ids` into this issue, which survives and keeps
    its status. Their reports move here; they keep their references and
    history, point here with `merged_into` and leave lists and the map.
    `version` is this issue's. Into itself or into a merged issue:
    `422 invalid_merge`. A blank reason: `422 reason_required`."""
    await consolidation.merge(db, principal, issue_id, body)
    return await service.get_detail(db, storage, principal, issue_id)


@router.post(
    "/{issue_id}/split",
    operation_id="issues_split",
    response_model=SplitResult,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def split_issue(
    principal: IssueMerger, db: DbSession, storage: Storage, issue_id: uuid.UUID, body: SplitRequest
) -> SplitResult:
    """Move `report_ids` to a new issue (`{"new_issue": true}`: same
    category, at the oldest moved report, status `reported`) or to an
    existing one (`{"issue_id"}`). Moving every report out is
    `422 cannot_empty_issue`."""
    target_id = await consolidation.split(db, principal, issue_id, body)
    return SplitResult(
        source=await service.get_detail(db, storage, principal, issue_id),
        target=await service.get_detail(db, storage, principal, target_id),
    )


@router.post(
    "/{issue_id}/related",
    operation_id="issues_add_related",
    response_model=RelatedIssueOut,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def add_related_issue(
    principal: IssueEditor,
    db: DbSession,
    storage: Storage,
    issue_id: uuid.UUID,
    body: RelatedRequest,
) -> RelatedIssueOut:
    """Mark another issue as related without merging (FR-060). Already
    related: `409 conflict`. Audited."""
    await consolidation.add_related(db, principal, issue_id, body)
    related = await service.related_issues(db, storage, principal, issue_id)
    return next(r for r in related if r.issue.id == body.issue_id)


@router.delete(
    "/{issue_id}/related/{other_id}",
    operation_id="issues_remove_related",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=error_responses(401, 403, 404, 422),
)
async def remove_related_issue(
    principal: IssueEditor, db: DbSession, issue_id: uuid.UUID, other_id: uuid.UUID
) -> Response:
    await consolidation.remove_related(db, principal, issue_id, other_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/{issue_id}/severity",
    operation_id="issues_set_severity",
    response_model=IssueDetail,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def set_severity(
    principal: IssueEditor,
    db: DbSession,
    storage: Storage,
    issue_id: uuid.UUID,
    body: SeverityOverride,
) -> IssueDetail:
    """Override the severity (a reason is required) or, with `null`, go back
    to the rules. Priority is recomputed. Audited."""
    await overrides.set_severity(db, principal, issue_id, body)
    return await service.get_detail(db, storage, principal, issue_id)


@router.patch(
    "/{issue_id}/priority",
    operation_id="issues_set_priority",
    response_model=IssueDetail,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def set_priority(
    principal: PrioritySetter,
    db: DbSession,
    storage: Storage,
    issue_id: uuid.UUID,
    body: PriorityOverride,
) -> IssueDetail:
    """Override the priority band (a reason is required) or, with `null`,
    go back to the computed band. The score is unchanged. Audited."""
    await overrides.set_priority(db, principal, issue_id, body)
    return await service.get_detail(db, storage, principal, issue_id)


@router.patch(
    "/{issue_id}/category",
    operation_id="issues_set_category",
    response_model=IssueDetail,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def set_category(
    principal: IssueEditor,
    db: DbSession,
    storage: Storage,
    issue_id: uuid.UUID,
    body: CategoryChange,
) -> IssueDetail:
    """Correct the category. The issue's reports follow and are marked
    `category_source: "operator"`; severity and priority are recomputed.
    Audited."""
    await overrides.set_category(db, principal, issue_id, body)
    return await service.get_detail(db, storage, principal, issue_id)
