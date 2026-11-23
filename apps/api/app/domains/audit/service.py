"""Writing and reading the audit trail."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import get_client, get_request_id
from app.core.pagination import PageParams, paginate, sort_clauses
from app.core.tenancy import current_tenant, rls_bypass
from app.domains.audit.models import AuditEvent
from app.domains.audit.schemas import AuditActor, AuditEventOut
from app.domains.rbac.principal import Principal
from app.domains.users.models import User

_UNSET: Any = object()


async def record(
    db: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    actor: Principal | None = None,
    actor_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = _UNSET,
) -> None:
    """Append an audit event in the current transaction.

    The event commits or rolls back together with the change it describes.
    The tenant defaults to the actor's, then to the session's current tenant.
    Platform-level events (tenant_id None) are written through the explicit
    bypass, since no tenant policy can match a NULL tenant.
    """
    if tenant_id is _UNSET:
        tenant_id = actor.tenant_id if actor is not None else current_tenant(db)
    client = get_client()
    event = AuditEvent(
        tenant_id=tenant_id,
        actor_id=actor.user_id if actor is not None else actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=before,
        after=after,
        request_id=get_request_id(),
        ip=client.ip,
        user_agent=client.user_agent[:400] if client.user_agent else None,
    )
    if tenant_id is None:
        async with rls_bypass(db, reason="platform audit event"):
            db.add(event)
            await db.flush()
    else:
        db.add(event)
        await db.flush()


SORTS = {"occurred_at": AuditEvent.occurred_at}


async def list_events(
    db: AsyncSession,
    params: PageParams,
    *,
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    sort: str | None = None,
) -> tuple[list[AuditEventOut], int]:
    stmt = select(AuditEvent, User.display_name).outerjoin(User, User.id == AuditEvent.actor_id)
    if actor_id is not None:
        stmt = stmt.where(AuditEvent.actor_id == actor_id)
    if action is not None:
        stmt = stmt.where(AuditEvent.action == action)
    if entity_type is not None:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    if occurred_from is not None:
        stmt = stmt.where(AuditEvent.occurred_at >= occurred_from)
    if occurred_to is not None:
        stmt = stmt.where(AuditEvent.occurred_at < occurred_to)
    stmt = stmt.order_by(
        *sort_clauses(sort, SORTS, default="-occurred_at", tiebreaker=AuditEvent.id)
    )

    rows, total = await paginate(db, stmt, params)
    items = [
        AuditEventOut(
            id=event.id,
            occurred_at=event.occurred_at,
            actor=AuditActor(id=event.actor_id, display_name=display_name)
            if event.actor_id is not None
            else None,
            action=event.action,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            before=event.before,
            after=event.after,
            request_id=event.request_id,
        )
        for event, display_name in rows
    ]
    return items, total
