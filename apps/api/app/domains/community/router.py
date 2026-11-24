"""Community support endpoints: "I face this too" and follow."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter

from app.core.db import DbSession
from app.core.errors import error_responses
from app.domains.community import service
from app.domains.community.schemas import SupportState
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal

router = APIRouter(tags=["community"])

Citizen = Annotated[Principal, require(Permission.REPORT_CREATE)]


@router.get(
    "/issues/{issue_id}/support",
    operation_id="issues_support_get",
    response_model=SupportState,
    responses=error_responses(401, 403, 404, 422),
)
async def get_support(principal: Citizen, db: DbSession, issue_id: uuid.UUID) -> SupportState:
    """The support count and whether the caller supports the issue."""
    return await service.get_state(db, principal, issue_id)


@router.post(
    "/issues/{issue_id}/support",
    operation_id="issues_support_add",
    response_model=SupportState,
    responses=error_responses(401, 403, 404, 422),
)
async def add_support(principal: Citizen, db: DbSession, issue_id: uuid.UUID) -> SupportState:
    """Say "I face this too": one per citizen per issue (repeating is harmless),
    and it follows the issue. Rejected or closed issues: `422
    invalid_transition`; a merged one: `422 issue_merged`. Support from
    citizens who did not report the issue adds a small, capped bonus to its
    priority (factor `community`)."""
    return await service.support(db, principal, issue_id)


@router.delete(
    "/issues/{issue_id}/support",
    operation_id="issues_support_remove",
    response_model=SupportState,
    responses=error_responses(401, 403, 404, 422),
)
async def remove_support(principal: Citizen, db: DbSession, issue_id: uuid.UUID) -> SupportState:
    """Withdraw support and stop following. Idempotent."""
    return await service.withdraw(db, principal, issue_id)
