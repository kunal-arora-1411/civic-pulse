"""The outbox dispatcher (ADR 0004, phase 4 task P4-03).

The table was written to from phase 3 onwards and read by nothing. These
tests pin the behaviour of the dispatcher that now drains it: every event
ends up dispatched exactly once, with a log row saying which channel carried
it and — while no external channel is configured — why nothing left the
building.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.domains.outbox.channels import NO_CHANNEL, Delivery
from app.domains.outbox.models import OutboxEvent
from app.domains.outbox.service import MAX_DELIVERY_ATTEMPTS, dispatch, purge_dispatched
from app.worker import celery_app
from tests.factories import create_tenant

NOW = datetime.now(UTC)


async def _event(
    conn: AsyncConnection,
    tenant_id: uuid.UUID,
    *,
    event_type: str = "issue.assigned",
    created_at: datetime | None = None,
    dispatched_at: datetime | None = None,
) -> uuid.UUID:
    return (
        await conn.execute(
            text(
                "INSERT INTO outbox_events "
                "(tenant_id, event_type, aggregate_type, aggregate_id, payload, created_at, "
                " dispatched_at) "
                "VALUES (:t, :e, 'issue', gen_random_uuid(), '{}'::jsonb, :c, :d) RETURNING id"
            ),
            {"t": tenant_id, "e": event_type, "c": created_at or NOW, "d": dispatched_at},
        )
    ).scalar_one()


async def _deliveries(conn: AsyncConnection, event_id: uuid.UUID) -> list[tuple[Any, ...]]:
    return list(
        (
            await conn.execute(
                text(
                    "SELECT channel, outcome, detail FROM outbox_deliveries "
                    "WHERE event_id = :e ORDER BY created_at, channel"
                ),
                {"e": event_id},
            )
        ).all()
    )


async def _attempts(conn: AsyncConnection, event_id: uuid.UUID) -> tuple[int, Any]:
    row = (
        await conn.execute(
            text("SELECT attempts, dispatched_at FROM outbox_events WHERE id = :e"),
            {"e": event_id},
        )
    ).one()
    return row[0], row[1]


class RecordingChannel:
    """A stand-in for the SMS/email/push adapters that providers will bring."""

    name = "recording"

    def __init__(self, *, handles: str = "issue.assigned", fail: bool = False) -> None:
        self.handled = handles
        self.fail = fail
        self.seen: list[uuid.UUID] = []

    def handles(self, event_type: str) -> bool:
        return event_type == self.handled

    async def deliver(self, event: OutboxEvent) -> Delivery:
        self.seen.append(event.id)
        if self.fail:
            raise RuntimeError("provider is down")
        return Delivery(channel=self.name)


async def test_a_dispatched_event_records_why_nothing_was_sent(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        event_id = await _event(conn, tenant.id)

    result = await dispatch(channels=())

    assert result.claimed >= 1
    async with owner_engine.connect() as conn:
        assert await _deliveries(conn, event_id) == [("none", "skipped", NO_CHANNEL)]
        _, dispatched_at = await _attempts(conn, event_id)
        assert dispatched_at is not None


async def test_a_configured_channel_receives_the_event(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        assigned = await _event(conn, tenant.id, event_type="issue.assigned")
        other = await _event(conn, tenant.id, event_type="issue.closed")

    channel = RecordingChannel(handles="issue.assigned")
    await dispatch(channels=(channel,))

    assert channel.seen == [assigned]
    async with owner_engine.connect() as conn:
        assert await _deliveries(conn, assigned) == [("recording", "delivered", None)]
        # The event no channel handles is still accounted for, not lost.
        assert await _deliveries(conn, other) == [("none", "skipped", NO_CHANNEL)]


async def test_a_failing_channel_is_retried_then_given_up_on(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        event_id = await _event(conn, tenant.id)

    channel = RecordingChannel(fail=True)
    for _ in range(MAX_DELIVERY_ATTEMPTS):
        await dispatch(channels=(channel,))

    # Every attempt was made, once per run, and then it stopped being retried.
    assert len(channel.seen) == MAX_DELIVERY_ATTEMPTS
    async with owner_engine.connect() as conn:
        attempts, dispatched_at = await _attempts(conn, event_id)
        assert attempts == MAX_DELIVERY_ATTEMPTS
        assert dispatched_at is not None
        outcomes = [row[1] for row in await _deliveries(conn, event_id)]
        assert outcomes == ["failed"] * MAX_DELIVERY_ATTEMPTS

    # A further run finds nothing to do, so a poison event cannot spin forever.
    assert (await dispatch(channels=(channel,))).claimed == 0


async def test_a_second_run_has_nothing_left_to_claim(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        await _event(conn, tenant.id)

    first = await dispatch(channels=())
    assert first.claimed >= 1
    assert (await dispatch(channels=())).claimed == 0


async def test_every_tenant_is_dispatched_not_only_one(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        one = await create_tenant(conn, name="City One")
        two = await create_tenant(conn, name="City Two")
        a = await _event(conn, one.id)
        b = await _event(conn, two.id)

    await dispatch(channels=())

    async with owner_engine.connect() as conn:
        for event_id in (a, b):
            _, dispatched_at = await _attempts(conn, event_id)
            assert dispatched_at is not None


async def test_retention_keeps_what_is_undispatched_and_what_is_recent(
    owner_engine: AsyncEngine,
) -> None:
    long_ago = NOW - timedelta(days=30)
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        stale = await _event(conn, tenant.id, dispatched_at=long_ago)
        recent = await _event(conn, tenant.id, dispatched_at=NOW - timedelta(days=1))
        waiting = await _event(conn, tenant.id, created_at=long_ago)

    removed = await purge_dispatched(older_than_days=7, now=NOW)

    assert removed >= 1
    async with owner_engine.connect() as conn:
        remaining = {
            row[0]
            for row in await conn.execute(
                text("SELECT id FROM outbox_events WHERE id = ANY(:ids)"),
                {"ids": [stale, recent, waiting]},
            )
        }
    # A dispatched event past retention goes; a recent one and one still
    # waiting to be delivered both stay.
    assert stale not in remaining
    assert {recent, waiting} <= remaining


async def test_purging_an_event_takes_its_delivery_log_with_it(
    owner_engine: AsyncEngine,
) -> None:
    long_ago = NOW - timedelta(days=30)
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        event_id = await _event(conn, tenant.id, dispatched_at=long_ago)

    await dispatch(channels=())
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE outbox_events SET dispatched_at = :d WHERE id = :e"),
            {"d": long_ago, "e": event_id},
        )

    await purge_dispatched(older_than_days=7, now=NOW)

    async with owner_engine.connect() as conn:
        assert await _deliveries(conn, event_id) == []


def test_the_dispatcher_is_scheduled_on_the_default_queue() -> None:
    entry = celery_app.conf.beat_schedule["outbox-dispatch"]
    assert entry["task"] == "civicpulse.outbox.dispatch"
    # Every 20 seconds: the longest a notification waits behind its commit.
    assert entry["schedule"] == 20.0
    celery_app.loader.import_default_modules()
    assert "civicpulse.outbox.dispatch" in celery_app.tasks
    routed = celery_app.amqp.router.route({}, "civicpulse.outbox.dispatch")["queue"].name
    assert routed == "default"
