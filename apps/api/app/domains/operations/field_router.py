"""The field worker's API (docs/api/phase-3-contract.md §3)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.pagination import PageParamsDep
from app.core.storage import Storage
from app.domains.operations import field
from app.domains.operations.models import WorkOrderState
from app.domains.operations.schemas import (
    ClosureRequestBody,
    DeclineBody,
    FieldWorkOrder,
    FieldWorkOrderPage,
    ProgressBody,
    VersionBody,
)
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal

router = APIRouter(prefix="/field/work-orders", tags=["field"])

FieldReader = Annotated[Principal, require(Permission.WORKORDER_READ_ASSIGNED)]
FieldWorker = Annotated[
    Principal, require(Permission.WORKORDER_READ_ASSIGNED, Permission.WORKORDER_UPDATE)
]
_ACTION_ERRORS = error_responses(401, 403, 404, 409, 422)


@router.get(
    "",
    operation_id="field_list_work_orders",
    response_model=FieldWorkOrderPage,
    responses=error_responses(401, 403, 422),
)
async def list_work_orders(
    principal: FieldReader,
    db: DbSession,
    storage: Storage,
    page: PageParamsDep,
    state: Annotated[
        list[WorkOrderState] | None,
        Query(description="Repeatable. Default: everything but `declined` and `cancelled`."),
    ] = None,
) -> FieldWorkOrderPage:
    """The caller's work orders, newest first."""
    items, total = await field.list_mine(db, storage, principal, page, state)
    return FieldWorkOrderPage(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/{work_order_id}",
    operation_id="field_get_work_order",
    response_model=FieldWorkOrder,
    responses=error_responses(401, 403, 404, 422),
)
async def get_work_order(
    principal: FieldReader, db: DbSession, storage: Storage, work_order_id: uuid.UUID
) -> FieldWorkOrder:
    """One of the caller's work orders; anyone else's is `404`."""
    return await field.get_mine(db, storage, principal, work_order_id)


@router.post(
    "/{work_order_id}/accept",
    operation_id="field_accept",
    response_model=FieldWorkOrder,
    responses=_ACTION_ERRORS,
)
async def accept(
    principal: FieldWorker,
    db: DbSession,
    storage: Storage,
    work_order_id: uuid.UUID,
    body: VersionBody,
) -> FieldWorkOrder:
    await field.accept(db, storage, principal, work_order_id, body)
    return await field.get_mine(db, storage, principal, work_order_id)


@router.post(
    "/{work_order_id}/decline",
    operation_id="field_decline",
    response_model=FieldWorkOrder,
    responses=_ACTION_ERRORS,
)
async def decline(
    principal: FieldWorker,
    db: DbSession,
    storage: Storage,
    work_order_id: uuid.UUID,
    body: DeclineBody,
) -> FieldWorkOrder:
    """With a reason. The issue goes back to `verified` for reassignment."""
    await field.decline(db, storage, principal, work_order_id, body)
    return await field.get_mine(db, storage, principal, work_order_id)


@router.post(
    "/{work_order_id}/start",
    operation_id="field_start",
    response_model=FieldWorkOrder,
    responses=_ACTION_ERRORS,
)
async def start(
    principal: FieldWorker,
    db: DbSession,
    storage: Storage,
    work_order_id: uuid.UUID,
    body: VersionBody,
) -> FieldWorkOrder:
    """The issue moves to `in_progress`."""
    await field.start(db, storage, principal, work_order_id, body)
    return await field.get_mine(db, storage, principal, work_order_id)


@router.post(
    "/{work_order_id}/progress",
    operation_id="field_progress",
    response_model=FieldWorkOrder,
    responses=_ACTION_ERRORS,
)
async def progress(
    principal: FieldWorker,
    db: DbSession,
    storage: Storage,
    work_order_id: uuid.UUID,
    body: ProgressBody,
) -> FieldWorkOrder:
    """A note, an optional location and optional evidence photos."""
    await field.progress(db, storage, principal, work_order_id, body)
    return await field.get_mine(db, storage, principal, work_order_id)


@router.post(
    "/{work_order_id}/request-closure",
    operation_id="field_request_closure",
    response_model=FieldWorkOrder,
    responses=_ACTION_ERRORS,
)
async def request_closure(
    principal: FieldWorker,
    db: DbSession,
    storage: Storage,
    work_order_id: uuid.UUID,
    body: ClosureRequestBody,
) -> FieldWorkOrder:
    """Needs an `after` photo on the work order or an allowed `reason_code`.
    The issue moves to `pending_verification`."""
    await field.request_closure(db, storage, principal, work_order_id, body)
    return await field.get_mine(db, storage, principal, work_order_id)
