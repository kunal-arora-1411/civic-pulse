"""The outbox dispatcher: claim undispatched events, deliver, mark them done.

Runs as a system job across every tenant, so it uses the RLS bypass. Each
batch is its own transaction — a crash mid-batch costs at most the messages
in flight, and the next run finds the rest (at-least-once delivery, ADR 0004).

Rows are claimed with `FOR UPDATE SKIP LOCKED`, so two dispatchers running at
once never hand the same event to a channel twice, and neither waits on the
other. The partial index on `created_at WHERE dispatched_at IS NULL` added in
migration 0007 keeps the scan cheap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log_fields
from app.core.tenancy import system_session
from app.domains.outbox.channels import NO_CHANNEL, Channel, Delivery, channels_for
from app.domains.outbox.models import DeliveryOutcome, OutboxDelivery, OutboxEvent

logger = logging.getLogger(__name__)

BATCH = 100
# After this many failed attempts an event is marked dispatched without
# having gone out. Poison messages stay visible in `outbox_deliveries` as
# `failed` rather than being retried forever.
MAX_DELIVERY_ATTEMPTS = 5


@dataclass(slots=True)
class DispatchResult:
    claimed: int = 0
    delivered: int = 0
    skipped: int = 0
    failed: int = 0
    abandoned: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "claimed": self.claimed,
            "delivered": self.delivered,
            "skipped": self.skipped,
            "failed": self.failed,
            "abandoned": self.abandoned,
        }


async def _claim(db: AsyncSession, limit: int) -> list[OutboxEvent]:
    rows = await db.execute(
        select(OutboxEvent)
        .where(OutboxEvent.dispatched_at.is_(None))
        .order_by(OutboxEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(rows.scalars().all())


async def _dispatch_one(
    db: AsyncSession,
    event: OutboxEvent,
    channels: tuple[Channel, ...] | None,
    result: DispatchResult,
) -> None:
    # `channels=None` means "use the registry"; `()` means "nothing is
    # configured", which is what a test passes to pin the skipped path.
    adapters = channels_for(event.event_type, channels)

    if not adapters:
        db.add(
            OutboxDelivery(
                tenant_id=event.tenant_id,
                event_id=event.id,
                channel="none",
                outcome=DeliveryOutcome.SKIPPED,
                detail=NO_CHANNEL,
            )
        )
        event.dispatched_at = datetime.now(UTC)
        result.skipped += 1
        await db.flush()
        return

    failed = False
    for adapter in adapters:
        try:
            delivery = await adapter.deliver(event)
        except Exception as exc:  # a channel must never abort the batch
            logger.warning(
                "outbox delivery failed",
                extra=log_fields(
                    event_id=str(event.id), event_type=event.event_type, channel=adapter.name
                ),
            )
            delivery = Delivery.failed(adapter.name, f"{type(exc).__name__}: {exc}")
        db.add(
            OutboxDelivery(
                tenant_id=event.tenant_id,
                event_id=event.id,
                channel=delivery.channel,
                outcome=delivery.outcome,
                detail=delivery.detail,
            )
        )
        match delivery.outcome:
            case DeliveryOutcome.DELIVERED:
                result.delivered += 1
            case DeliveryOutcome.SKIPPED:
                result.skipped += 1
            case DeliveryOutcome.FAILED:
                failed = True

    event.attempts = (event.attempts or 0) + 1
    if not failed:
        event.dispatched_at = datetime.now(UTC)
    elif event.attempts >= MAX_DELIVERY_ATTEMPTS:
        # Out of attempts: stop retrying, but leave the failure on record.
        event.dispatched_at = datetime.now(UTC)
        result.abandoned += 1
    else:
        # Left undispatched on purpose, so the next tick tries again.
        result.failed += 1
    await db.flush()


async def dispatch(
    *,
    limit: int = BATCH,
    channels: tuple[Channel, ...] | None = None,
    drain: bool = True,
) -> DispatchResult:
    """Deliver what is waiting. `drain` keeps claiming batches until empty."""
    result = DispatchResult()
    while True:
        async with system_session(reason="outbox: dispatch") as db:
            events = await _claim(db, limit)
            if not events:
                break
            result.claimed += len(events)
            for event in events:
                await _dispatch_one(db, event, channels, result)
        if len(events) < limit or not drain:
            break
    logger.info("outbox dispatch finished", extra=log_fields(**result.as_dict()))
    return result


async def purge_dispatched(*, older_than_days: int, now: datetime | None = None) -> int:
    """Drop dispatched events past retention. Deliveries cascade with them."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=older_than_days)
    async with system_session(reason="outbox: retention") as db:
        gone = await db.execute(
            delete(OutboxEvent).where(
                OutboxEvent.dispatched_at.is_not(None), OutboxEvent.dispatched_at < cutoff
            )
        )
        return int(gone.rowcount or 0)  # pyright: ignore[reportAttributeAccessIssue]
