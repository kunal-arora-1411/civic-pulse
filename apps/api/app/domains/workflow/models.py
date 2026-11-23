"""The configurable issue state machine (PRD FR-052, FR-053, FR-081)."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.domains.rbac.roles import Role
from app.domains.workflow.statuses import IssueStatus, sql_in

_STATUSES = sql_in(IssueStatus)
_ROLES = sql_in(Role)


class StatusTransition(TimestampMixin, Base):
    """One allowed move from a status to another.

    `allowed_roles` lists the roles that may perform it through the API.
    `system_only` moves are made by the platform itself (assignment, for
    example) and the status endpoint refuses them whatever the caller's role.
    """

    __tablename__ = "status_transitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "from_status", "to_status"),
        CheckConstraint(f"from_status IN ({_STATUSES})", name="from_status_values"),
        CheckConstraint(f"to_status IN ({_STATUSES})", name="to_status_values"),
        CheckConstraint("from_status <> to_status", name="not_a_loop"),
        CheckConstraint(
            f"allowed_roles <@ ARRAY[{_ROLES}]::varchar[]", name="allowed_roles_values"
        ),
        CheckConstraint(
            "NOT system_only OR cardinality(allowed_roles) = 0", name="system_only_has_no_roles"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    from_status: Mapped[str] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    allowed_roles: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), default=list, server_default=text("'{}'::varchar[]")
    )
    requires_reason: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    system_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
