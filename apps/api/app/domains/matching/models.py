"""Duplicate matching records: every candidate considered, and review tasks."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.domains.workflow.statuses import sql_in


class Decision(StrEnum):
    AUTO_LINKED = "auto_linked"
    SENT_TO_REVIEW = "sent_to_review"
    REJECTED_CANDIDATE = "rejected_candidate"
    CHOSEN_BY_REVIEWER = "chosen_by_reviewer"
    NOT_CHOSEN = "not_chosen"


class Feedback(StrEnum):
    CORRECT = "correct"
    INCORRECT = "incorrect"


class MatchDecision(Base):
    """One candidate issue considered for one report, and what became of it.

    Every candidate gets a row, so any decision can be explained afterwards
    (FR-037), and the rows double as labelled data for tuning (FR-035).
    `decided_by` is NULL when the platform decided.
    """

    __tablename__ = "match_decisions"
    __table_args__ = (
        UniqueConstraint("report_id", "candidate_issue_id"),
        ForeignKeyConstraint(
            ["tenant_id", "report_id"],
            ["reports.tenant_id", "reports.id"],
            ondelete="RESTRICT",
            name="fk_match_decisions_tenant_report",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "candidate_issue_id"],
            ["civic_issues.tenant_id", "civic_issues.id"],
            ondelete="RESTRICT",
            name="fk_match_decisions_tenant_candidate_issue",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "decided_by"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
            name="fk_match_decisions_tenant_decided_by",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "feedback_by"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
            name="fk_match_decisions_tenant_feedback_by",
        ),
        CheckConstraint(f"decision IN ({sql_in(Decision)})", name="decision_values"),
        CheckConstraint(
            f"feedback IS NULL OR feedback IN ({sql_in(Feedback)})", name="feedback_values"
        ),
        CheckConstraint("rank >= 1", name="rank_positive"),
        CheckConstraint("score BETWEEN 0 AND 1", name="score_range"),
        Index("ix_match_decisions_candidate_issue_id", "candidate_issue_id"),
        Index("ix_match_decisions_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    report_id: Mapped[uuid.UUID] = mapped_column()
    candidate_issue_id: Mapped[uuid.UUID] = mapped_column()
    rank: Mapped[int] = mapped_column(SmallInteger)
    score: Mapped[float] = mapped_column(Float)
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB)
    decision: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str | None] = mapped_column(String(100))
    decided_by: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    feedback: Mapped[str | None] = mapped_column(String(16))
    feedback_by: Mapped[uuid.UUID | None] = mapped_column()
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    feedback_note: Mapped[str | None] = mapped_column(Text)


class ReviewStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ReviewResolution(StrEnum):
    LINKED = "linked"
    NEW_ISSUE = "new_issue"


class ReviewTask(TimestampMixin, Base):
    """An ambiguous match waiting for a person to decide (FR-031)."""

    __tablename__ = "review_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "report_id"],
            ["reports.tenant_id", "reports.id"],
            ondelete="RESTRICT",
            name="fk_review_tasks_tenant_report",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "resolved_issue_id"],
            ["civic_issues.tenant_id", "civic_issues.id"],
            ondelete="RESTRICT",
            name="fk_review_tasks_tenant_resolved_issue",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "resolved_by"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
            name="fk_review_tasks_tenant_resolved_by",
        ),
        CheckConstraint(f"status IN ({sql_in(ReviewStatus)})", name="status_values"),
        CheckConstraint(
            f"resolution IS NULL OR resolution IN ({sql_in(ReviewResolution)})",
            name="resolution_values",
        ),
        CheckConstraint(
            "(status = 'open') = (resolution IS NULL AND resolved_at IS NULL)",
            name="resolved_has_resolution",
        ),
        # At most one open task per report.
        Index(
            "uq_review_tasks_open_report",
            "report_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_review_tasks_tenant_status_created", "tenant_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    report_id: Mapped[uuid.UUID] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), default=ReviewStatus.OPEN)
    resolution: Mapped[str | None] = mapped_column(String(16))
    resolved_issue_id: Mapped[uuid.UUID | None] = mapped_column()
    resolved_by: Mapped[uuid.UUID | None] = mapped_column()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
