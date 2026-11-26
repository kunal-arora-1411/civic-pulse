from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.pagination import PageParamsDep
from app.domains.outbox import admin
from app.domains.outbox.schemas import DeadLetter, DeadLetterPage
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal

router = APIRouter(prefix="/admin/outbox", tags=["admin"])

ConfigManager = Annotated[Principal, require(Permission.CONFIG_MANAGE)]


@router.get(
    "/dead-letters",
    operation_id="admin_list_dead_letters",
    response_model=DeadLetterPage,
    responses=error_responses(401, 403, 422),
)
async def list_dead_letters(_: ConfigManager, db: DbSession, page: PageParamsDep) -> DeadLetterPage:
    """Events the dispatcher stopped retrying, newest first, with every
    delivery attempt. Payloads are never shown."""
    return await admin.list_dead_letters(db, page)


@router.post(
    "/dead-letters/{event_id}/retry",
    operation_id="admin_retry_dead_letter",
    response_model=DeadLetter,
    responses=error_responses(401, 403, 404, 422),
)
async def retry_dead_letter(
    principal: ConfigManager, db: DbSession, event_id: uuid.UUID
) -> DeadLetter:
    """Queue it again with a fresh set of attempts; channels that already
    delivered it are not asked twice. Audited."""
    return await admin.retry(db, principal, event_id)
