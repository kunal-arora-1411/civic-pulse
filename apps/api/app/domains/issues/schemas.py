from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.pagination import Page
from app.domains.categories.schemas import CategoryRef
from app.domains.issues.models import EventType, SeveritySource, Visibility
from app.domains.priority.rules import PriorityBand, SeverityLevel
from app.domains.reports.schemas import ReportStaffView, WardRef
from app.domains.workflow.statuses import IssueStatus


class PointOut(BaseModel):
    lat: float
    lng: float


class SeverityOut(BaseModel):
    level: SeverityLevel
    source: SeveritySource = Field(description="`rule`, or `override` when staff set it.")
    reason: str | None = Field(
        description="How the rules got there, or the override's reason (staff wording)."
    )


class PriorityFactorOut(BaseModel):
    factor: str = Field(examples=["severity"])
    value: Any = Field(description="The raw input: a level, a count, days, or true/false.")
    normalized: float = Field(description="0-1")
    points: float = Field(description="normalized x the factor's weight")
    explanation_key: str = Field(
        examples=["priority.severity"], description="Localised by the client."
    )


class PriorityOut(BaseModel):
    score: float = Field(description="0-100, from the rules (an override doesn't change it).")
    band: PriorityBand = Field(description="The effective band: the override when present.")
    computed_band: PriorityBand
    overridden: bool
    override_reason: str | None


class PriorityDetailOut(PriorityOut):
    factors: list[PriorityFactorOut] = Field(description="Largest contribution first.")


class IssueListItem(BaseModel):
    id: uuid.UUID
    reference: str = Field(examples=["CP-26-000123"])
    status: IssueStatus
    category: CategoryRef
    location: PointOut
    address_text: str | None
    ward: WardRef | None
    report_count: int
    unique_reporter_count: int
    severity: SeverityOut
    priority: PriorityOut | None = Field(
        description="Null only until the issue's priority is first computed (seconds)."
    )
    thumb_url: str | None
    created_at: datetime
    updated_at: datetime
    version: int


class IssuePage(Page[IssueListItem]):
    pass


class IssueRefOut(BaseModel):
    id: uuid.UUID
    reference: str


class EventActor(BaseModel):
    id: uuid.UUID
    display_name: str | None


class TimelineEvent(BaseModel):
    """The staff timeline: every event, internal ones included."""

    id: uuid.UUID
    at: datetime
    type: EventType
    from_status: IssueStatus | None
    to_status: IssueStatus | None
    reason: str | None
    public_note: str | None
    visibility: Visibility
    actor: EventActor | None
    related_issue: IssueRefOut | None = Field(description="The other issue in a merge or split.")
    data: dict[str, Any] | None = Field(
        description="Details for the staff timeline: moved report ids, old and new values."
    )


class AllowedTransition(BaseModel):
    to_status: IssueStatus
    requires_reason: bool


class RelatedIssueOut(BaseModel):
    issue: IssueListItem
    note: str | None


class IssueDetail(IssueListItem):
    priority: PriorityDetailOut | None = Field(
        description="Null only until the issue's priority is first computed (seconds)."
    )
    reports: list[ReportStaffView] = Field(description="Oldest first.")
    timeline: list[TimelineEvent] = Field(description="Oldest first.")
    allowed_transitions: list[AllowedTransition] = Field(
        description="What the caller may move this issue to right now."
    )
    merged_into: IssueRefOut | None = Field(
        description="Set when this issue was merged into another: redirect there."
    )
    related: list[RelatedIssueOut] = Field(description="Issues marked as related (FR-060).")


def _clean(value: str | None) -> str | None:
    return (value.strip() or None) if value is not None else None


class _Change(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(
        default=None, max_length=2000, description="Internal; never shown to citizens."
    )
    version: int = Field(ge=1, description="The `version` you last saw (optimistic locking).")

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str | None) -> str | None:
        return _clean(value)


class MergeRequest(_Change):
    source_issue_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=20, description="Merged into the issue in the path."
    )

    @field_validator("source_issue_ids")
    @classmethod
    def _unique(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Each issue can only be listed once.")
        return value


class NewIssueTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_issue: Literal[True]


class ExistingIssueTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: uuid.UUID


class SplitRequest(_Change):
    report_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    target: NewIssueTarget | ExistingIssueTarget

    @field_validator("report_ids")
    @classmethod
    def _unique(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Each report can only be listed once.")
        return value


class SplitResult(BaseModel):
    source: IssueDetail
    target: IssueDetail


class RelatedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: uuid.UUID
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _strip_note(cls, value: str | None) -> str | None:
        return _clean(value)


class SeverityOverride(_Change):
    severity: SeverityLevel | None = Field(
        description="A level to override with (a reason is required), or null to go back "
        "to the rules."
    )


class PriorityOverride(_Change):
    band: PriorityBand | None = Field(
        description="A band to override with (a reason is required), or null to go back to "
        "the computed band."
    )


class CategoryChange(_Change):
    category_id: uuid.UUID


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: IssueStatus
    reason: str | None = Field(
        default=None, max_length=2000, description="Internal; never shown to citizens."
    )
    public_note: str | None = Field(
        default=None, max_length=2000, description="Shown to the reporters on their timeline."
    )
    version: int = Field(ge=1, description="The `version` you last saw (optimistic locking).")

    @field_validator("reason", "public_note")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


# --- GeoJSON -------------------------------------------------------------------------------


class PointGeometry(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float] = Field(description="`[lng, lat]`")


class IssueFeatureProperties(BaseModel):
    id: uuid.UUID
    reference: str
    status: IssueStatus
    category_code: str
    report_count: int
    severity: SeverityLevel
    priority_band: PriorityBand | None = Field(description="The effective band.")


class IssueFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: uuid.UUID
    geometry: PointGeometry
    properties: IssueFeatureProperties


class IssueFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[IssueFeature]
    truncated: bool = Field(description="True when more issues matched than the cap returns.")
