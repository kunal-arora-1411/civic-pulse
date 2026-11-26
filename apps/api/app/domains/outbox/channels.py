"""Channel adapters the outbox dispatcher hands events to.

An adapter turns one domain event into one message on one channel. The seam
exists so choosing a provider (MSG91 or Gupshup for SMS, SES or Postmark for
email, VAPID for web push) is a new class, here or beside it, not a change to
the dispatcher, the task or the beat schedule.

Email is the first one: `app/domains/outbox/email.py` delivers an assignment
to the assignee over SMTP whenever `SMTP_HOST` is set. With no relay
configured it is absent from the registry, so every event is still recorded as
`skipped` with the reason — which is honest about what did and did not leave
the building.

The **in-app inbox needs no adapter**: notifications are written by database
triggers in the same transaction as the change they describe (migration 0008,
plus the SLA scanner), so that channel is already delivered by the time an
event reaches the outbox.
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
#
# Recorded against every event while no external channel exists, so the
# delivery log distinguishes "nothing to send it on" from "nothing to send".
NO_CHANNEL = "no external channel is configured"


def default_channels() -> tuple[Channel, ...]:
    """The channels this deployment can actually deliver on.

    Imported lazily: the email channel imports `Delivery` from this module, so
    a module-level import would be a cycle.
    """
    from app.core.mail import get_mailer
    from app.domains.outbox.email import EmailChannel

    channels: list[Channel] = []
    mailer = get_mailer()
    if mailer is not None:
        channels.append(EmailChannel(mailer))
    return tuple(channels)


def channels_for(event_type: str, channels: tuple[Channel, ...] | None = None) -> list[Channel]:
    adapters = default_channels() if channels is None else channels
    return [c for c in adapters if c.handles(event_type)]
