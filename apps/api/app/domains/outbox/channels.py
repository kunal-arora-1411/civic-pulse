"""Channel adapters the outbox dispatcher hands events to.

An adapter turns one domain event into one message on one channel. The seam
exists so choosing a provider (MSG91 or Gupshup for SMS, SES or Postmark for
email, VAPID for web push) is a new class here, not a change to the
dispatcher, the task or the beat schedule.

Nothing is registered yet. The **in-app inbox needs no adapter**: notifications
are written by database triggers in the same transaction as the change they
describe (migration 0008, plus the SLA scanner), so that channel is already
delivered by the time an event reaches the outbox. What remains is the
external channels, and each needs a provider decision first — see
docs/STATUS.md. Until then every event is recorded as `skipped` with the
reason, which is honest about what did and did not leave the building.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.domains.outbox.models import DeliveryOutcome, OutboxEvent


@dataclass(frozen=True, slots=True)
class Delivery:
    """What an adapter did, recorded in `outbox_deliveries`."""

    channel: str
    outcome: DeliveryOutcome = DeliveryOutcome.DELIVERED
    detail: str | None = None

    @classmethod
    def skipped(cls, channel: str, reason: str) -> Delivery:
        return cls(channel=channel, outcome=DeliveryOutcome.SKIPPED, detail=reason)

    @classmethod
    def failed(cls, channel: str, reason: str) -> Delivery:
        # Column is String(300); a provider error can be longer than that.
        return cls(channel=channel, outcome=DeliveryOutcome.FAILED, detail=reason[:300])


@runtime_checkable
class Channel(Protocol):
    """One delivery channel.

    `handles` decides whether this channel is about a given event type, so a
    new event type does not require editing the dispatcher. `deliver` must be
    idempotent on repeated calls for the same event id, because the
    dispatcher retries (at-least-once).
    """

    name: str

    def handles(self, event_type: str) -> bool: ...

    async def deliver(self, event: OutboxEvent) -> Delivery: ...


# Populated when a provider is chosen and its credentials exist. Order is
# irrelevant: every matching channel is attempted.
CHANNELS: tuple[Channel, ...] = ()

# Recorded against every event while no external channel exists, so the
# delivery log distinguishes "nothing to send it on" from "nothing to send".
NO_CHANNEL = "no external channel is configured"


def channels_for(event_type: str, channels: tuple[Channel, ...] | None = None) -> list[Channel]:
    return [c for c in (CHANNELS if channels is None else channels) if c.handles(event_type)]
