"""Dead letters for administrators: what never went out, and sending it again.

Read through the caller's tenant session, so RLS limits a municipality to its
own events (platform sign-in codes have no tenant and never appear here).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.pagination import PageParams, paginate
from app.domains.audit import service as audit
from app.domains.outbox import service
from app.domains.outbox.models import OutboxDelivery, OutboxEvent
from app.domains.outbox.schemas import DeadLetter, DeadLetterPage, DeliveryAttempt
from app.domains.rbac.principal import Principal


async def _attempts(
    db: AsyncSession, ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[DeliveryAttempt]]:
    by_event: dict[uuid.UUID, list[DeliveryAttempt]] = {i: [] for i in ids}
    if not ids:
        return by_event
    rows = await db.scalars(
        select(OutboxDelivery)
        .where(OutboxDelivery.event_id.in_(ids))
        .order_by(OutboxDelivery.created_at)
    )
    for row in rows.all():
        by_event[row.event_id].append(DeliveryAttempt.model_validate(row))
    return by_event


def _out(event: OutboxEvent, attempts: list[DeliveryAttempt]) -> DeadLetter:
    return DeadLetter(
        id=event.id,
        event_type=event.event_type,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        attempts=event.attempts,
        last_error=event.last_error,
        created_at=event.created_at,
        dead_lettered_at=event.dead_lettered_at,
        deliveries=attempts,
    )


async def list_dead_letters(db: AsyncSession, page: PageParams) -> DeadLetterPage:
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.dead_lettered_at.is_not(None))
        .order_by(OutboxEvent.dead_lettered_at.desc(), OutboxEvent.id)
    )
    rows, total = await paginate(db, stmt, page)
    events = [row[0] for row in rows]
    attempts = await _attempts(db, [e.id for e in events])
    return DeadLetterPage(
        items=[_out(e, attempts[e.id]) for e in events],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


async def retry(db: AsyncSession, principal: Principal, event_id: uuid.UUID) -> DeadLetter:
    event = await db.scalar(
        select(OutboxEvent)
        .where(OutboxEvent.id == event_id, OutboxEvent.dead_lettered_at.is_not(None))
        .with_for_update()
    )
    if event is None:
        raise NotFound()
    before = {
        "dead_lettered_at": event.dead_lettered_at.isoformat() if event.dead_lettered_at else None,
        "attempts": event.attempts,
    }
    await service.retry_dead_letter(db, event)
    await audit.record(
        db,
        action="outbox.dead_letter_retried",
        entity_type="outbox_event",
        entity_id=event.id,
        actor=principal,
        before=before,
        after={"dead_lettered_at": None, "attempts": 0, "event_type": event.event_type},
    )
    return _out(event, (await _attempts(db, [event.id]))[event.id])
