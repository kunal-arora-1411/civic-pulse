from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query
from sqlalchemy.exc import IntegrityError

from app.core.db import DbSession
from app.core.errors import Conflict, error_responses
from app.core.pagination import PageParamsDep
from app.domains.audit import service
from app.domains.audit.schemas import (
    AuditChainStatus,
    AuditChainVerificationOut,
    AuditChainVerificationPage,
    AuditChainVerificationRequest,
    AuditCheckpointPage,
    AuditEventPage,
    VerificationStatus,
)
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.jobs import JobsDep

router = APIRouter(prefix="/admin/audit-events", tags=["admin"])

# The chain lives beside the event list it describes, under its own prefix, because
# the two are read by the same people and documented together.
chain_router = APIRouter(prefix="/admin/audit-chain", tags=["admin"])


@router.get(
    "",
    operation_id="admin_list_audit_events",
    response_model=AuditEventPage,
    responses=error_responses(401, 403, 422),
)
async def list_audit_events(
    _: Annotated[Principal, require(Permission.AUDIT_READ)],
    db: DbSession,
    page: PageParamsDep,
    actor_id: uuid.UUID | None = None,
    action: Annotated[str | None, Query(max_length=100)] = None,
    entity_type: Annotated[str | None, Query(max_length=50)] = None,
    entity_id: Annotated[str | None, Query(max_length=100)] = None,
    occurred_from: Annotated[
        datetime | None, Query(alias="from", description="Inclusive lower bound (ISO 8601).")
    ] = None,
    occurred_to: Annotated[
        datetime | None, Query(alias="to", description="Exclusive upper bound (ISO 8601).")
    ] = None,
    sort: Annotated[
        str | None, Query(description="`occurred_at` or `-occurred_at` (default).")
    ] = None,
) -> AuditEventPage:
    items, total = await service.list_events(
        db,
        page,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        sort=sort,
    )
    return AuditEventPage(items=items, total=total, limit=page.limit, offset=page.offset)


@chain_router.get(
    "",
    operation_id="admin_get_audit_chain",
    response_model=AuditChainStatus,
    responses=error_responses(401, 403),
)
async def get_audit_chain(
    _: Annotated[Principal, require(Permission.AUDIT_READ)],
    db: DbSession,
) -> AuditChainStatus:
    """The head, the newest signed checkpoint, and the last verification.

    `healthy: false` means rows moved or vanished after they were sealed. It is
    deliberately not part of `/ready`: taking the API out of a load balancer would
    stop a city accepting reports, which is worse than a flagged audit trail.
    """
    return await service.chain_status(db)


@chain_router.post(
    "/verifications",
    operation_id="admin_start_audit_chain_verification",
    response_model=AuditChainVerificationOut,
    status_code=202,
    responses=error_responses(401, 403, 409, 422, 503),
)
async def start_audit_chain_verification(
    principal: Annotated[Principal, require(Permission.AUDIT_READ)],
    db: DbSession,
    body: AuditChainVerificationRequest,
    jobs: JobsDep,
    background: BackgroundTasks,
) -> AuditChainVerificationOut:
    """Queue a verification of a window of this tenant's chain.

    Only one run may be in flight per tenant: the database enforces it with a
    partial unique index, and the second request gets a 409 rather than quietly
    starting a duplicate scan of the same rows.
    """
    try:
        view = await service.start_verification(db, principal, body)
    except IntegrityError as exc:
        raise Conflict("a verification of this chain is already in progress") from exc

    # Runs after the transaction commits, so the worker finds the row it is told
    # about. Jobs whose broker call fails are abandoned by the sweeper's next run,
    # and the in-flight index would otherwise block every later request.
    background.add_task(_dispatch, jobs, view.id)
    return view


async def _dispatch(jobs: JobsDep, verification_id: uuid.UUID) -> None:
    await jobs.verify_audit_chain(verification_id)


@chain_router.get(
    "/verifications",
    operation_id="admin_list_audit_chain_verifications",
    response_model=AuditChainVerificationPage,
    responses=error_responses(401, 403, 422),
)
async def list_audit_chain_verifications(
    _: Annotated[Principal, require(Permission.AUDIT_READ)],
    db: DbSession,
    page: PageParamsDep,
    status: VerificationStatus | None = None,
    sort: Annotated[
        str | None, Query(description="`started_at` or `-started_at` (default).")
    ] = None,
) -> AuditChainVerificationPage:
    items, total = await service.list_verifications(db, page, status=status, sort=sort)
    return AuditChainVerificationPage(
        items=items, total=total, limit=page.limit, offset=page.offset
    )


@chain_router.get(
    "/verifications/{verification_id}",
    operation_id="admin_get_audit_chain_verification",
    response_model=AuditChainVerificationOut,
    responses=error_responses(401, 403, 404),
)
async def get_audit_chain_verification(
    _: Annotated[Principal, require(Permission.AUDIT_READ)],
    db: DbSession,
    verification_id: uuid.UUID,
) -> AuditChainVerificationOut:
    """One run. A run belonging to another tenant is a 404, not a 403: the row is
    invisible under row-level security, and no error may reveal that it exists."""
    return await service.get_verification(db, verification_id)


@chain_router.get(
    "/checkpoints",
    operation_id="admin_list_audit_checkpoints",
    response_model=AuditCheckpointPage,
    responses=error_responses(401, 403, 422),
)
async def list_audit_checkpoints(
    _: Annotated[Principal, require(Permission.AUDIT_READ)],
    db: DbSession,
    page: PageParamsDep,
) -> AuditCheckpointPage:
    """Signed seals of this chain's head, newest first, each with its signature
    checked against the configured keys."""
    items, total = await service.list_checkpoints(db, page)
    return AuditCheckpointPage(items=items, total=total, limit=page.limit, offset=page.offset)
