"""SLA targets (migration 0010). Deadlines live on `civic_issues`."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.domains.priority.rules import PriorityBand
from app.domains.workflow.statuses import sql_in


class SlaTarget(Base):
    """How long a category's issues may stay open before they breach.

    A row with no `priority_band` applies to every band the category has no
    narrower row for. `escalate_after_hours` is how long after the breach the
    escalation moves from the department's supervisors to the municipal
    admins. The `sla_schedule` trigger reads this table to set `due_at`.
    """

    __tablename__ = "sla_targets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            ondelete="CASCADE",
            name="fk_sla_targets_tenant_category",
        ),
        UniqueConstraint(
            "tenant_id", "category_id", "priority_band", postgresql_nulls_not_distinct=True
        ),
        CheckConstraint(
            f"priority_band IS NULL OR priority_band IN ({sql_in(PriorityBand)})",
            name="priority_band_values",
        ),
        CheckConstraint("resolve_hours BETWEEN 1 AND 8760", name="resolve_hours_range"),
        CheckConstraint(
            "escalate_after_hours BETWEEN 1 AND 8760", name="escalate_after_hours_range"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    category_id: Mapped[uuid.UUID] = mapped_column()
    priority_band: Mapped[str | None] = mapped_column(String(16))
    resolve_hours: Mapped[int] = mapped_column(Integer)
    escalate_after_hours: Mapped[int] = mapped_column(Integer)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
