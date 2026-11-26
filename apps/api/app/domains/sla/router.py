from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter

from app.core.db import DbSession
from app.core.errors import error_responses
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.sla import service
from app.domains.sla.schemas import SlaTargets, SlaTargetsUpdate

router = APIRouter(prefix="/admin", tags=["admin"])

ConfigReader = Annotated[Principal, require(Permission.CONFIG_READ)]
ConfigManager = Annotated[Principal, require(Permission.CONFIG_MANAGE)]


@router.get(
    "/sla-targets",
    operation_id="admin_get_sla_targets",
    response_model=SlaTargets,
    responses=error_responses(401, 403),
)
async def get_sla_targets(_: ConfigReader, db: DbSession) -> SlaTargets:
    """Resolution targets per category, optionally narrowed to a priority band."""
    return await service.list_targets(db)


@router.put(
    "/sla-targets",
    operation_id="admin_update_sla_targets",
    response_model=SlaTargets,
    responses=error_responses(401, 403, 422),
)
async def update_sla_targets(
    principal: ConfigManager, db: DbSession, body: SlaTargetsUpdate
) -> SlaTargets:
    """Replace the whole set. One target per category and band (a null band
    covers the rest). Every open issue is rescheduled against it. Audited."""
    return await service.replace_targets(db, principal, body)
