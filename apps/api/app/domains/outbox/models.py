"""Domain events waiting to be delivered (docs/adr/0004-outbox.md)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.domains.workflow.statuses import sql_in


class OutboxEvent(Base):
    """One event, written in the same transaction as the change it reports.

    The dispatcher claims undispatched rows whose `next_attempt_at` has come,
    and sets `dispatched_at` once every channel has had it. An event that
    keeps failing is parked as a dead letter (`dead_lettered_at`) for an
    administrator to inspect and send again.

    `tenant_id` is NULL only for a platform administrator's sign-in code;
    such rows are reachable through the RLS bypass alone.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_outbox_events_undispatched",
            "created_at",
            postgresql_where=text("dispatched_at IS NULL AND dead_lettered_at IS NULL"),
        ),
        Index(
            "ix_outbox_events_dead_lettered",
            "dead_lettered_at",
            postgresql_where=text("dead_lettered_at IS NOT NULL"),
        ),
        # Every tenant-scoped table carries this so a composite foreign key
        # can reference (tenant_id, id) and keep a row in one tenant.
        UniqueConstraint("tenant_id", "id", name="uq_outbox_events_tenant_id_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT")
    )
    event_type: Mapped[str] = mapped_column(String(64))
    aggregate_type: Mapped[str] = mapped_column(String(32))
    aggregate_id: Mapped[uuid.UUID] = mapped_column()
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A delivery that failed is retried with backoff until this reaches
    # `MAX_DELIVERY_ATTEMPTS`; then the row becomes a dead letter, so a
    # poison event cannot be retried forever but is not lost either.
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))


class DeliveryOutcome(StrEnum):
    DELIVERED = "delivered"
    # No channel is configured for this event type yet (the external
    # providers are not chosen). Recorded, not hidden: the log then shows
    # exactly which events would have gone out and nowhere to send them.
    SKIPPED = "skipped"
    FAILED = "failed"


class OutboxDelivery(Base):
    """One row per (event, channel) attempt, so a send can be accounted for.

    Delivery is at-least-once: an adapter may be retried, so consumers
    de-duplicate on the event `id` (ADR 0004).
    """

    __tablename__ = "outbox_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["outbox_events.tenant_id", "outbox_events.id"],
            ondelete="CASCADE",
            name="fk_outbox_deliveries_tenant_event",
        ),
        CheckConstraint(f"outcome IN ({sql_in(DeliveryOutcome)})", name="outcome_values"),
        Index("ix_outbox_deliveries_event", "event_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT")
    )
    # The composite key above keeps a delivery in its event's tenant; this
    # one carries the cascade for tenant-less (platform sign-in) events.
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outbox_events.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(16))
    detail: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
