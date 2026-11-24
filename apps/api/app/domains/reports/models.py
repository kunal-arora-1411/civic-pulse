"""Citizen reports: one submission each (PRD §10.1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
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

MAX_DESCRIPTION_LENGTH = 2000


class ReportStatus(StrEnum):
    ACCEPTED = "accepted"
    WITHDRAWN = "withdrawn"


class LocationSource(StrEnum):
    GPS = "gps"
    PIN = "pin"
    MANUAL = "manual"


class CategorySource(StrEnum):
    """Who chose the report's category (FR-021: AI corrections are labels)."""

    CITIZEN = "citizen"  # no AI suggestion was used
    AI_ACCEPTED = "ai_accepted"  # the citizen kept the top suggestion
    AI_CORRECTED = "ai_corrected"  # the citizen picked something else
    OPERATOR = "operator"  # staff corrected it afterwards


class MatchingStatus(StrEnum):
    """Where duplicate matching stands for a report (Phase 2)."""

    PENDING = "pending"  # not decided yet; no issue
    REVIEW = "review"  # waiting for a human; no issue
    LINKED = "linked"  # joined an existing issue
    NEW_ISSUE = "new_issue"  # started an issue of its own


class Report(TimestampMixin, Base):
    """A single citizen submission. Reports are never deleted: merges and
    withdrawals keep the row (PRD §10.2), so the app role has no DELETE."""

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reference"),
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "reporter_id"],
            ["users.tenant_id", "users.id"],
            ondelete="RESTRICT",
            name="fk_reports_tenant_reporter",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            ondelete="RESTRICT",
            name="fk_reports_tenant_category",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "issue_id"],
            ["civic_issues.tenant_id", "civic_issues.id"],
            ondelete="RESTRICT",
            name="fk_reports_tenant_issue",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ward_id"],
            ["jurisdictions.tenant_id", "jurisdictions.id"],
            ondelete="RESTRICT",
            name="fk_reports_tenant_ward",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "classification_id"],
            ["classifications.tenant_id", "classifications.id"],
            ondelete="RESTRICT",
            name="fk_reports_tenant_classification",
        ),
        CheckConstraint(f"status IN ({sql_in(ReportStatus)})", name="status_values"),
        CheckConstraint(
            f"category_source IN ({sql_in(CategorySource)})", name="category_source_values"
        ),
        CheckConstraint(
            f"matching_status IN ({sql_in(MatchingStatus)})", name="matching_status_values"
        ),
        # A report has an issue exactly when matching has placed it.
        CheckConstraint(
            "(matching_status IN ('pending', 'review')) = (issue_id IS NULL)",
            name="issue_matches_status",
        ),
        CheckConstraint(
            f"location_source IN ({sql_in(LocationSource)})", name="location_source_values"
        ),
        CheckConstraint(
            f"char_length(description) <= {MAX_DESCRIPTION_LENGTH}", name="description_length"
        ),
        CheckConstraint(
            "location_accuracy_m IS NULL OR location_accuracy_m >= 0", name="accuracy_positive"
        ),
        CheckConstraint("jsonb_typeof(details) = 'object'", name="details_is_object"),
        Index("ix_reports_tenant_reporter_created", "tenant_id", "reporter_id", "created_at"),
        Index("ix_reports_issue_id", "issue_id"),
        Index("ix_reports_location", "location", postgresql_using="gist"),
        # The matching watchdog looks for reports stuck in `pending`.
        Index(
            "ix_reports_matching_pending",
            "created_at",
            postgresql_where=text("matching_status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    reference: Mapped[str] = mapped_column(String(20))
    reporter_id: Mapped[uuid.UUID] = mapped_column()
    category_id: Mapped[uuid.UUID] = mapped_column()
    # NULL while matching is pending or the report waits in review.
    issue_id: Mapped[uuid.UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), default=ReportStatus.ACCEPTED)
    description: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    location: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326, spatial_index=False))
    location_accuracy_m: Mapped[float | None] = mapped_column(Float)
    location_source: Mapped[str] = mapped_column(String(16))
    address_text: Mapped[str | None] = mapped_column(String(500))
    ward_id: Mapped[uuid.UUID | None] = mapped_column()
    client_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classification_id: Mapped[uuid.UUID | None] = mapped_column()
    category_source: Mapped[str] = mapped_column(
        String(16), default=CategorySource.CITIZEN, server_default=text("'citizen'")
    )
    matching_status: Mapped[str] = mapped_column(String(16), default=MatchingStatus.PENDING)
