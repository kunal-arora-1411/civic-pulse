"""Civic issues, their timeline, and the per-tenant reference counters."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.domains.priority.rules import PriorityBand, SeverityLevel
from app.domains.workflow.statuses import IssueStatus, sql_in


class SeveritySource(StrEnum):
    RULE = "rule"
    OVERRIDE = "override"


class CivicIssue(TimestampMixin, Base):
    """The underlying real-world problem that one or more reports describe.

    `report_count` and `unique_reporter_count` are maintained in the same
    transaction as the reports they count (PRD §10.2). `version` increments
    on every change and backs optimistic locking. `search_document` is
    maintained by triggers (see migration 0002) from the issue reference and
    address plus every linked report's reference, address and description.
    """

    __tablename__ = "civic_issues"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reference"),
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            ondelete="RESTRICT",
            name="fk_civic_issues_tenant_category",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ward_id"],
            ["jurisdictions.tenant_id", "jurisdictions.id"],
            ondelete="RESTRICT",
            name="fk_civic_issues_tenant_ward",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "cover_media_id"],
            ["media_assets.tenant_id", "media_assets.id"],
            ondelete="RESTRICT",
            name="fk_civic_issues_tenant_cover_media",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["tenant_id", "merged_into_id"],
            ["civic_issues.tenant_id", "civic_issues.id"],
            ondelete="RESTRICT",
            name="fk_civic_issues_tenant_merged_into",
        ),
        CheckConstraint(f"status IN ({sql_in(IssueStatus)})", name="status_values"),
        CheckConstraint(
            "merged_into_id IS NULL OR merged_into_id <> id", name="not_merged_into_self"
        ),
        CheckConstraint(
            "report_count >= 0 AND unique_reporter_count BETWEEN 0 AND report_count",
            name="counts_consistent",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(f"severity IN ({sql_in(SeverityLevel)})", name="severity_values"),
        CheckConstraint(
            f"severity_source IN ({sql_in(SeveritySource)})", name="severity_source_values"
        ),
        CheckConstraint(
            "severity_source = 'rule' OR severity_reason IS NOT NULL", name="override_has_reason"
        ),
        CheckConstraint(
            f"priority_band IS NULL OR priority_band IN ({sql_in(PriorityBand)})",
            name="priority_band_values",
        ),
        CheckConstraint(
            f"priority_override_band IS NULL OR priority_override_band IN ({sql_in(PriorityBand)})",
            name="priority_override_values",
        ),
        CheckConstraint(
            "(priority_override_band IS NULL) = (priority_override_reason IS NULL)",
            name="priority_override_has_reason",
        ),
        CheckConstraint(
            "priority_score IS NULL OR priority_score BETWEEN 0 AND 100",
            name="priority_score_range",
        ),
        Index("ix_civic_issues_location", "location", postgresql_using="gist"),
        Index("ix_civic_issues_search_document", "search_document", postgresql_using="gin"),
        Index("ix_civic_issues_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("ix_civic_issues_tenant_created", "tenant_id", "created_at"),
        Index("ix_civic_issues_tenant_updated", "tenant_id", "updated_at"),
        Index("ix_civic_issues_tenant_category", "tenant_id", "category_id"),
        Index("ix_civic_issues_tenant_ward", "tenant_id", "ward_id"),
        Index("ix_civic_issues_tenant_report_count", "tenant_id", "report_count"),
        Index("ix_civic_issues_merged_into_id", "merged_into_id"),
        Index("ix_civic_issues_tenant_priority_score", "tenant_id", "priority_score"),
        # Issues waiting for their first priority computation.
        Index(
            "ix_civic_issues_priority_pending",
            "created_at",
            postgresql_where=text("priority_computed_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    reference: Mapped[str] = mapped_column(String(20))
    category_id: Mapped[uuid.UUID] = mapped_column()
    status: Mapped[str] = mapped_column(String(32), default=IssueStatus.REPORTED)
    location: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326, spatial_index=False))
    address_text: Mapped[str | None] = mapped_column(String(500))
    ward_id: Mapped[uuid.UUID | None] = mapped_column()
    report_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    unique_reporter_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # Severity (FR-038): computed from the category's rules unless a person
    # overrode it (`severity_source = override`, with their reason).
    severity: Mapped[str] = mapped_column(
        String(16), default=SeverityLevel.MEDIUM, server_default=text("'medium'")
    )
    severity_source: Mapped[str] = mapped_column(
        String(16), default=SeveritySource.RULE, server_default=text("'rule'")
    )
    severity_reason: Mapped[str | None] = mapped_column(Text)
    # Priority (FR-039 to FR-044): the computed score and band with the
    # factors behind them, and an optional manual band that takes effect
    # over the computed one. NULL score: not computed yet.
    priority_score: Mapped[float | None] = mapped_column(Numeric(5, 2, asdecimal=False))
    priority_band: Mapped[str | None] = mapped_column(String(16))
    priority_override_band: Mapped[str | None] = mapped_column(String(16))
    priority_override_reason: Mapped[str | None] = mapped_column(Text)
    priority_factors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB(none_as_null=True))
    priority_computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    cover_media_id: Mapped[uuid.UUID | None] = mapped_column()
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    search_document: Mapped[Any] = mapped_column(
        TSVECTOR, server_default=text("''::tsvector"), deferred=True
    )
    # Set when this issue was merged into another (FR-033). A merged issue
    # keeps its reference and history but has no reports and drops out of
    # lists, the map and matching; reading it points at the survivor.
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column()


class EventType(StrEnum):
    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    NOTE = "note"
    # Phase 2
    REPORT_LINKED = "report_linked"  # a report joined this issue
    MERGED = "merged"  # another issue was merged into this one
    MERGED_INTO = "merged_into"  # this issue was merged into another
    SPLIT = "split"  # reports moved out of (or into) this issue
    CATEGORY_CHANGED = "category_changed"
    SEVERITY_CHANGED = "severity_changed"
    PRIORITY_CHANGED = "priority_changed"


class Visibility(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"


class IssueEvent(Base):
    """One entry in an issue's timeline (PRD FR-054, "Issue Update").

    Append-only: the app role may only SELECT and INSERT. Citizens see
    `public` events, and from those only the status change and the public
    note; never `reason`, never the actor.
    """

    __tablename__ = "issue_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "issue_id"],
            ["civic_issues.tenant_id", "civic_issues.id"],
            ondelete="RESTRICT",
            name="fk_issue_events_tenant_issue",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "report_id"],
            ["reports.tenant_id", "reports.id"],
            ondelete="RESTRICT",
            name="fk_issue_events_tenant_report",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "related_issue_id"],
            ["civic_issues.tenant_id", "civic_issues.id"],
            ondelete="RESTRICT",
            name="fk_issue_events_tenant_related_issue",
        ),
        CheckConstraint(f"type IN ({sql_in(EventType)})", name="type_values"),
        CheckConstraint(f"visibility IN ({sql_in(Visibility)})", name="visibility_values"),
        CheckConstraint(
            "type <> 'status_changed' OR to_status IS NOT NULL", name="status_change_has_target"
        ),
        Index("ix_issue_events_issue_created", "issue_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    issue_id: Mapped[uuid.UUID] = mapped_column()
    report_id: Mapped[uuid.UUID | None] = mapped_column()
    type: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text)
    public_note: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Phase 2: the other issue in a merge or split, and structured details
    # (moved report ids, old and new values) for the staff timeline.
    related_issue_id: Mapped[uuid.UUID | None] = mapped_column()
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))


class IssueRelation(Base):
    """Two issues marked as related without merging them (FR-060).

    One row per unordered pair: `issue_id` is always the smaller id.
    """

    __tablename__ = "issue_relations"
    __table_args__ = (
        PrimaryKeyConstraint("issue_id", "related_issue_id"),
        ForeignKeyConstraint(
            ["tenant_id", "issue_id"],
            ["civic_issues.tenant_id", "civic_issues.id"],
            ondelete="RESTRICT",
            name="fk_issue_relations_tenant_issue",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "related_issue_id"],
            ["civic_issues.tenant_id", "civic_issues.id"],
            ondelete="RESTRICT",
            name="fk_issue_relations_tenant_related_issue",
        ),
        CheckConstraint("issue_id < related_issue_id", name="ordered_pair"),
        Index("ix_issue_relations_related_issue_id", "related_issue_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    issue_id: Mapped[uuid.UUID] = mapped_column()
    related_issue_id: Mapped[uuid.UUID] = mapped_column()
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReferenceKind(StrEnum):
    REPORT = "report"
    ISSUE = "issue"


class ReferenceCounter(Base):
    """The last reference number handed out, per tenant, kind and year."""

    __tablename__ = "reference_counters"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "kind", "year"),
        CheckConstraint(f"kind IN ({sql_in(ReferenceKind)})", name="kind_values"),
        CheckConstraint("last_value >= 0", name="last_value_positive"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(16))
    year: Mapped[int] = mapped_column(SmallInteger)
    last_value: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
