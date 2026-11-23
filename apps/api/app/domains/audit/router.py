from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.pagination import PageParamsDep
from app.domains.audit import service
from app.domains.audit.schemas import AuditEventPage
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal

router = APIRouter(prefix="/admin/audit-events", tags=["admin"])


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
