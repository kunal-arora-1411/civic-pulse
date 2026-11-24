"""Assignments, work orders, closure requests and verifications (Phase 3)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.domains.workflow.statuses import sql_in


def _tenant_fk(table: str, column: str, target: str, name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", column],
        [f"{target}.tenant_id", f"{target}.id"],
        ondelete="RESTRICT",
        name=f"fk_{table}_tenant_{name}",
    )


class AssignmentEnd(StrEnum):
    REASSIGNED = "reassigned"
    DECLINED = "declined"


class IssueAssignment(Base):
    """Who holds an issue. At most one open (`ended_at IS NULL`) per issue;
    the ended rows are the assignment history (FR-062)."""

    __tablename__ = "issue_assignments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        _tenant_fk("issue_assignments", "issue_id", "civic_issues", "issue"),
        _tenant_fk("issue_assignments", "team_id", "teams", "team"),
        _tenant_fk("issue_assignments", "assignee_id", "users", "assignee"),
        CheckConstraint(
            f"end_reason IS NULL OR end_reason IN ({sql_in(AssignmentEnd)})",
            name="end_reason_values",
        ),
        CheckConstraint("(ended_at IS NULL) = (end_reason IS NULL)", name="ended_has_reason"),
        Index(
            "uq_issue_assignments_open",
            "issue_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        Index("ix_issue_assignments_issue_created", "issue_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    issue_id: Mapped[uuid.UUID] = mapped_column()
    team_id: Mapped[uuid.UUID] = mapped_column()
    assignee_id: Mapped[uuid.UUID | None] = mapped_column()
    note: Mapped[str | None] = mapped_column(Text)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(16))


class WorkOrderState(StrEnum):
    PENDING_ACCEPTANCE = "pending_acceptance"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETION_REQUESTED = "completion_requested"
    DONE = "done"
    DECLINED = "declined"
    CANCELLED = "cancelled"


OPEN_WORK_ORDER_STATES = (
    WorkOrderState.PENDING_ACCEPTANCE,
    WorkOrderState.ACCEPTED,
    WorkOrderState.IN_PROGRESS,
    WorkOrderState.COMPLETION_REQUESTED,
)


class WorkOrder(TimestampMixin, Base):
    """The field side of an assignment to a person (FR-063 to FR-066).

    `version` backs optimistic locking for offline field apps (§16).
    """

    __tablename__ = "work_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        _tenant_fk("work_orders", "issue_id", "civic_issues", "issue"),
        _tenant_fk("work_orders", "assignment_id", "issue_assignments", "assignment"),
        _tenant_fk("work_orders", "assignee_id", "users", "assignee"),
        CheckConstraint(f"state IN ({sql_in(WorkOrderState)})", name="state_values"),
        CheckConstraint(
            "state <> 'declined' OR decline_reason IS NOT NULL", name="declined_reason"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_work_orders_assignee_state", "tenant_id", "assignee_id", "state"),
        Index("ix_work_orders_issue_id", "issue_id"),
        Index(
            "uq_work_orders_open_per_issue",
            "issue_id",
            unique=True,
            postgresql_where=text(
                "state IN ('pending_acceptance', 'accepted', 'in_progress', 'completion_requested')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    issue_id: Mapped[uuid.UUID] = mapped_column()
    assignment_id: Mapped[uuid.UUID] = mapped_column()
    assignee_id: Mapped[uuid.UUID] = mapped_column()
    state: Mapped[str] = mapped_column(String(32), default=WorkOrderState.PENDING_ACCEPTANCE)
    decline_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))


class ClosureState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ClosureRequest(Base):
    """A request to close an issue, with its evidence or reason (FR-070).

    At most one pending per issue. Verifications belong to one request, so
    each closure round counts citizens afresh.
    """

    __tablename__ = "closure_requests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        _tenant_fk("closure_requests", "issue_id", "civic_issues", "issue"),
        _tenant_fk("closure_requests", "work_order_id", "work_orders", "work_order"),
        CheckConstraint(f"state IN ({sql_in(ClosureState)})", name="state_values"),
        Index(
            "uq_closure_requests_pending",
            "issue_id",
            unique=True,
            postgresql_where=text("state = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    issue_id: Mapped[uuid.UUID] = mapped_column()
    work_order_id: Mapped[uuid.UUID | None] = mapped_column()
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reason_code: Mapped[str | None] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), default=ClosureState.PENDING)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class VerificationOutcome(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class IssueVerification(Base):
    """One citizen's answer for one closure round (FR-072, FR-073)."""

    __tablename__ = "issue_verifications"
    __table_args__ = (
        UniqueConstraint("closure_request_id", "user_id"),
        _tenant_fk("issue_verifications", "issue_id", "civic_issues", "issue"),
        _tenant_fk("issue_verifications", "closure_request_id", "closure_requests", "closure"),
        _tenant_fk("issue_verifications", "user_id", "users", "user"),
        CheckConstraint(f"outcome IN ({sql_in(VerificationOutcome)})", name="outcome_values"),
        Index("ix_issue_verifications_issue_id", "issue_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    issue_id: Mapped[uuid.UUID] = mapped_column()
    closure_request_id: Mapped[uuid.UUID] = mapped_column()
    user_id: Mapped[uuid.UUID] = mapped_column()
    outcome: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
