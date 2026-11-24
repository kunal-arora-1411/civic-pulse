from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks

from app.core.db import DbSession
from app.core.errors import error_responses
from app.domains.config import service
from app.domains.config.models import ConfigKey
from app.domains.config.schemas import ClosureConfig, MatchingConfig, PriorityConfig
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.jobs import JobsDep

router = APIRouter(prefix="/admin", tags=["admin"])

ConfigReader = Annotated[Principal, require(Permission.CONFIG_READ)]
ConfigManager = Annotated[Principal, require(Permission.CONFIG_MANAGE)]


@router.get(
    "/matching-config",
    operation_id="admin_get_matching_config",
    response_model=MatchingConfig,
    responses=error_responses(401, 403),
)
async def get_matching_config(_: ConfigReader, db: DbSession) -> MatchingConfig:
    """Duplicate-matching weights and thresholds in effect (defaults if never set)."""
    return await service.matching_config(db)


@router.put(
    "/matching-config",
    operation_id="admin_update_matching_config",
    response_model=MatchingConfig,
    responses=error_responses(401, 403, 422),
)
async def update_matching_config(
    principal: ConfigManager, db: DbSession, body: MatchingConfig
) -> MatchingConfig:
    """Replace the whole document; a field left out goes back to its default.
    Weights must add up to 1 and `review` can't exceed `auto`. Audited."""
    return await service.replace(db, principal, ConfigKey.MATCHING, body)


@router.get(
    "/priority-config",
    operation_id="admin_get_priority_config",
    response_model=PriorityConfig,
    responses=error_responses(401, 403),
)
async def get_priority_config(_: ConfigReader, db: DbSession) -> PriorityConfig:
    """Priority weights, scaling and bands in effect (defaults if never set)."""
    return await service.priority_config(db)


@router.put(
    "/priority-config",
    operation_id="admin_update_priority_config",
    response_model=PriorityConfig,
    responses=error_responses(401, 403, 422),
)
async def update_priority_config(
    principal: ConfigManager,
    db: DbSession,
    jobs: JobsDep,
    background: BackgroundTasks,
    body: PriorityConfig,
) -> PriorityConfig:
    """Replace the whole document; a field left out goes back to its default.
    Weights must add up to 100 and the bands must fall from critical to
    medium. Audited. Every issue is then recomputed in the background."""
    saved = await service.replace(db, principal, ConfigKey.PRIORITY, body)
    assert principal.tenant_id is not None
    background.add_task(jobs.recompute_priorities, principal.tenant_id)
    return saved


@router.get(
    "/closure-config",
    operation_id="admin_get_closure_config",
    response_model=ClosureConfig,
    responses=error_responses(401, 403),
)
async def get_closure_config(_: ConfigReader, db: DbSession) -> ClosureConfig:
    """Resolution window and confirmation threshold in effect (defaults if never set)."""
    return await service.closure_config(db)


@router.put(
    "/closure-config",
    operation_id="admin_update_closure_config",
    response_model=ClosureConfig,
    responses=error_responses(401, 403, 422),
)
async def update_closure_config(
    principal: ConfigManager, db: DbSession, body: ClosureConfig
) -> ClosureConfig:
    """Replace the whole document; a field left out goes back to its default. Audited."""
    return await service.replace(db, principal, ConfigKey.CLOSURE, body)
