"""Domain events waiting to be delivered (docs/adr/0004-outbox.md)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class OutboxEvent(Base):
    """One event, written in the same transaction as the change it reports.

    Phase 3 only writes rows; the Phase 4 dispatcher reads undispatched ones
    and sets `dispatched_at`.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_outbox_events_undispatched",
            "created_at",
            postgresql_where=text("dispatched_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    event_type: Mapped[str] = mapped_column(String(64))
    aggregate_type: Mapped[str] = mapped_column(String(32))
    aggregate_id: Mapped[uuid.UUID] = mapped_column()
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
