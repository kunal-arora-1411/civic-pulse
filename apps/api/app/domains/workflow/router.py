from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.pagination import PageParamsDep
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.workflow import service
from app.domains.workflow.schemas import TransitionPage

router = APIRouter(prefix="/admin/workflow", tags=["admin"])


@router.get(
    "/transitions",
    operation_id="admin_list_transitions",
    response_model=TransitionPage,
    responses=error_responses(401, 403, 422),
)
async def list_transitions(
    _: Annotated[Principal, require(Permission.CONFIG_READ)],
    db: DbSession,
    page: PageParamsDep,
) -> TransitionPage:
    """The tenant's status transitions in lifecycle order. Read-only in Phase 1."""
    items, total = await service.list_transitions(db, page)
    return TransitionPage(items=items, total=total, limit=page.limit, offset=page.offset)
