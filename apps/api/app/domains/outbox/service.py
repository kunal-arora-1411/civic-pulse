"""The outbox dispatcher: claim due events, deliver, mark them done.

Runs as a system job across every tenant, so it uses the RLS bypass. Each
batch is its own transaction — a crash mid-batch costs at most the messages
in flight, and the next run finds the rest (at-least-once delivery, ADR 0004).

Rows are claimed with `FOR UPDATE SKIP LOCKED`, so two dispatchers running at
once never hand the same event to a channel twice, and neither waits on the
other. The partial index on undispatched, live events keeps the scan cheap.

A failed delivery backs off exponentially (`next_attempt_at`) and is retried
only on the channels that have not yet delivered it, so a working email relay
is not asked twice because SMS was down. After `MAX_DELIVERY_ATTEMPTS` the
event becomes a dead letter: no longer retried, never purged by retention,
and listed for administrators, who can send it again (`retry_dead_letter`).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log_fields
from app.core.tenancy import system_session
from app.domains.outbox.channels import NO_CHANNEL, Channel, Delivery, channels_for
from app.domains.outbox.models import DeliveryOutcome, OutboxDelivery, OutboxEvent

logger = logging.getLogger(__name__)

BATCH = 100
# After this many failed attempts an event becomes a dead letter. Its
# failures stay visible in `outbox_deliveries`, and an administrator can
# send it again.
MAX_DELIVERY_ATTEMPTS = 5
# Backoff after the n-th failure: 30 s, 1 min, 2 min, 4 min, capped at an
# hour. Four retries span about eight minutes, which rides out a provider
# blip without leaving a one-time password undelivered past its lifetime.
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 3600


def backoff(attempts: int) -> timedelta:
    """How long to wait after the `attempts`-th failed try."""
    seconds = BACKOFF_BASE_SECONDS * 2 ** max(attempts - 1, 0)
    return timedelta(seconds=min(seconds, BACKOFF_MAX_SECONDS))


@dataclass(slots=True)
class DispatchResult:
    claimed: int = 0
    delivered: int = 0
    skipped: int = 0
    failed: int = 0
    dead_lettered: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "claimed": self.claimed,
            "delivered": self.delivered,
            "skipped": self.skipped,
            "failed": self.failed,
            "dead_lettered": self.dead_lettered,
        }


def _due(now: datetime) -> tuple[Any, ...]:
    """Live, undelivered events whose backoff has passed."""
    return (
        OutboxEvent.dispatched_at.is_(None),
        OutboxEvent.dead_lettered_at.is_(None),
        or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= now),
    )


async def _claim(db: AsyncSession, limit: int, now: datetime) -> list[OutboxEvent]:
    rows = await db.execute(
        select(OutboxEvent)
        .where(*_due(now))
        .order_by(OutboxEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(rows.scalars().all())


async def _already_delivered(db: AsyncSession, event: OutboxEvent) -> set[str]:
    """Channels that carried this event on an earlier try."""
    rows = await db.scalars(
        select(OutboxDelivery.channel).where(
            OutboxDelivery.event_id == event.id,
            OutboxDelivery.outcome == DeliveryOutcome.DELIVERED,
        )
    )
    return set(rows.all())


def _log(event: OutboxEvent, delivery: Delivery) -> OutboxDelivery:
    return OutboxDelivery(
        tenant_id=event.tenant_id,
        event_id=event.id,
        channel=delivery.channel,
        outcome=delivery.outcome,
        detail=delivery.detail,
    )


async def _dispatch_one(
    db: AsyncSession,
    event: OutboxEvent,
    channels: tuple[Channel, ...] | None,
    result: DispatchResult,
    now: datetime,
) -> None:
    # `channels=None` means "use the registry"; `()` means "nothing is
    # configured", which is what a test passes to pin the skipped path.
    adapters = channels_for(event.event_type, channels)

    if not adapters:
        db.add(_log(event, Delivery.skipped("none", NO_CHANNEL)))
        event.dispatched_at = now
        result.skipped += 1
        await db.flush()
        return

    done = await _already_delivered(db, event)
    failed = False
    last_error: str | None = None
    for adapter in adapters:
        if adapter.name in done:
            continue
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
        db.add(_log(event, delivery))
        match delivery.outcome:
            case DeliveryOutcome.DELIVERED:
                result.delivered += 1
            case DeliveryOutcome.SKIPPED:
                result.skipped += 1
            case DeliveryOutcome.FAILED:
                failed = True
                last_error = delivery.detail

    event.attempts = (event.attempts or 0) + 1
    if not failed:
        event.dispatched_at = now
        event.next_attempt_at = None
        event.last_error = None
    elif event.attempts >= MAX_DELIVERY_ATTEMPTS:
        # Out of attempts: stop retrying, but keep it where people can see it.
        event.dead_lettered_at = now
        event.last_error = last_error
        result.dead_lettered += 1
        logger.warning(
            "outbox event dead-lettered",
            extra=log_fields(
                event_id=str(event.id), event_type=event.event_type, attempts=event.attempts
            ),
        )
    else:
        # Left undispatched on purpose; a later tick tries again once the
        # backoff has passed.
        event.next_attempt_at = now + backoff(event.attempts)
        event.last_error = last_error
        result.failed += 1
    await db.flush()


async def dispatch(
    *,
    limit: int = BATCH,
    channels: tuple[Channel, ...] | None = None,
    drain: bool = True,
    now: datetime | None = None,
) -> DispatchResult:
    """Deliver what is due. `drain` keeps claiming batches until empty.

    `now` is the dispatcher's clock; tests move it forward to step past a
    backoff instead of waiting for it.
    """
    result = DispatchResult()
    while True:
        moment = now or datetime.now(UTC)
        async with system_session(reason="outbox: dispatch") as db:
            events = await _claim(db, limit, moment)
            if not events:
                break
            result.claimed += len(events)
            for event in events:
                await _dispatch_one(db, event, channels, result, moment)
        if len(events) < limit or not drain:
            break
    logger.info("outbox dispatch finished", extra=log_fields(**result.as_dict()))
    return result


async def dispatch_event(
    event_id: uuid.UUID, *, channels: tuple[Channel, ...] | None = None
) -> DispatchResult:
    """Deliver one event now, if it is still due.

    Used where waiting for the next tick would be noticed: a sign-in code is
    sent straight after the request commits. An event another dispatcher
    holds, or one already sent, is left alone.
    """
    result = DispatchResult()
    moment = datetime.now(UTC)
    async with system_session(reason="outbox: deliver one event") as db:
        event = await db.scalar(
            select(OutboxEvent)
            .where(OutboxEvent.id == event_id, *_due(moment))
            .with_for_update(skip_locked=True)
        )
        if event is not None:
            result.claimed = 1
            await _dispatch_one(db, event, channels, result, moment)
    return result


async def retry_dead_letter(db: AsyncSession, event: OutboxEvent) -> None:
    """Put a dead letter back in the queue with a fresh set of attempts.

    Channels that already delivered it are still skipped on the next try.
    The caller found the row (RLS decides whose it may see) and audits.
    """
    event.dead_lettered_at = None
    event.attempts = 0
    event.next_attempt_at = None
    await db.flush()


async def purge_dispatched(*, older_than_days: int, now: datetime | None = None) -> int:
    """Drop dispatched events past retention. Deliveries cascade with them.

    Dead letters are never dispatched, so they stay until someone acts.
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(days=older_than_days)
    async with system_session(reason="outbox: retention") as db:
        gone = await db.execute(
            delete(OutboxEvent).where(
                OutboxEvent.dispatched_at.is_not(None), OutboxEvent.dispatched_at < cutoff
            )
        )
        return int(gone.rowcount or 0)  # pyright: ignore[reportAttributeAccessIssue]
