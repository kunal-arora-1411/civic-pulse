from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Header, Query, Response, status
from fastapi.responses import JSONResponse

from app.core import idempotency
from app.core.db import DbSession
from app.core.errors import ServiceUnavailable, error_responses
from app.core.pagination import PageParamsDep
from app.core.ratelimit import enforce_window
from app.core.redis import get_redis
from app.core.storage import Storage
from app.domains.auth.dependencies import CurrentPrincipal
from app.domains.config import service as config_service
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.reports import service, withdraw
from app.domains.reports.schemas import (
    MyReportPage,
    ReportCreate,
    ReportOwnerView,
    ReportStaffView,
    ReportView,
)
from app.domains.workflow.statuses import IssueStatus
from app.jobs import JobsDep

logger = logging.getLogger(__name__)
router = APIRouter(tags=["reports"])

RequiredIdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
        pattern=r"^[\x21-\x7e]+$",
        description="Required. One key per submission attempt: a retry with the same key and "
        "body returns the original report instead of creating another.",
    ),
]


async def _enforce_report_limits(db: DbSession, principal: Principal) -> None:
    """Per-user submission limits, from the tenant's own configuration (or
    its defaults). Unlike the OTP limits these fail open: an unreachable
    Redis must not stop citizens reporting problems."""
    limits = await config_service.report_limits_config(db)
    key = f"ratelimit:reports:{principal.tenant_id}:{principal.user_id}"
    try:
        await enforce_window(get_redis(), f"{key}:hour", limits.max_per_hour, 3600)
        await enforce_window(get_redis(), f"{key}:day", limits.max_per_day, 86400)
    except ServiceUnavailable:
        logger.warning("report rate limit skipped: limiter unavailable")


@router.post(
    "/reports",
    operation_id="reports_create",
    response_model=ReportOwnerView,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 422, 429),
)
async def create_report(
    principal: Annotated[Principal, require(Permission.REPORT_CREATE)],
    db: DbSession,
    storage: Storage,
    body: ReportCreate,
    idempotency_key: RequiredIdempotencyKey,
    jobs: JobsDep,
    background: BackgroundTasks,
) -> Any:
    """Submit a report. It is saved with `matching_status: "pending"` and no
    issue; duplicate matching runs in the background and then links it to
    an existing issue, sends it to review or starts a new issue."""
    claim = await idempotency.begin(
        db,
        key=idempotency_key,
        scope="POST /reports",
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        body=body,
    )
    if isinstance(claim, Response):
        return await _replay(db, storage, claim)

    await _enforce_report_limits(db, principal)
    report_id = await service.create_report(db, principal, body)
    view = await service.get_owner_view(db, storage, report_id)
    assert view is not None
    await idempotency.complete(db, claim, status.HTTP_201_CREATED, view)
    # Runs after the transaction commits, so the worker finds the report.
    assert principal.tenant_id is not None
    background.add_task(jobs.match_report, report_id, principal.tenant_id)
    return view


@router.get(
    "/users/me/reports",
    operation_id="reports_list_mine",
    response_model=MyReportPage,
    responses=error_responses(401, 403, 422),
)
async def list_my_reports(
    principal: Annotated[Principal, require(Permission.REPORT_READ_OWN)],
    db: DbSession,
    storage: Storage,
    page: PageParamsDep,
    status: Annotated[
        list[IssueStatus] | None,
        Query(description="Filter by the linked issue's status. Repeatable."),
    ] = None,
) -> MyReportPage:
    """The caller's own reports, newest first."""
    items, total = await service.list_mine(db, storage, principal, page, statuses=status or [])
    return MyReportPage(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/reports/{report_id}",
    operation_id="reports_get",
    response_model=ReportView,
    responses=error_responses(401, 403, 404, 422),
)
async def get_report(
    principal: CurrentPrincipal, db: DbSession, storage: Storage, report_id: uuid.UUID
) -> ReportOwnerView | ReportStaffView:
    """The reporter gets the owner view (`view: "owner"`). Staff with
    `report:read` whose jurisdiction covers the report get the staff view
    (`view: "staff"`); reporter phone and email only with `user:manage`.
    Anyone else gets 404."""
    return await service.get_report_view(db, storage, principal, report_id)


async def _replay(db: DbSession, storage: Storage, stored: Response) -> Response:
    """Replay a submission, but with fresh content.

    The stored body holds signed media URLs that expire after minutes, and a
    status that may have moved on, so the replay re-renders the same report
    and keeps the original status code and the replay header.
    """
    body = json.loads(bytes(stored.body))
    view = await service.get_owner_view(db, storage, uuid.UUID(body["id"]))
    if view is None:  # pragma: no cover - reports are never deleted
        return stored
    return JSONResponse(
        view.model_dump(mode="json"),
        status_code=stored.status_code,
        headers={idempotency.REPLAY_HEADER: "true"},
    )


@router.post(
    "/reports/{report_id}/withdraw",
    operation_id="reports_withdraw",
    response_model=ReportOwnerView,
    responses=error_responses(401, 403, 404, 422),
)
async def withdraw_report(
    principal: Annotated[Principal, require(Permission.REPORT_READ_OWN)],
    db: DbSession,
    storage: Storage,
    report_id: uuid.UUID,
) -> ReportOwnerView:
    """Withdraw your own report. It is kept (and stays on its issue's
    history) but no longer counts. Refused while matching is still placing
    it, or once the issue is resolved or closed."""
    await withdraw.withdraw(db, principal, report_id)
    view = await service.get_owner_view(db, storage, report_id)
    assert view is not None
    return view
