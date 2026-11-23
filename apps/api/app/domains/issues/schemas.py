from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.pagination import Page
from app.domains.categories.schemas import CategoryRef
from app.domains.issues.models import EventType, Visibility
from app.domains.reports.schemas import ReportStaffView, WardRef
from app.domains.workflow.statuses import IssueStatus


class PointOut(BaseModel):
    lat: float
    lng: float


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
    severity: str | None = Field(description="Null until Phase 2.")
    priority: str | None = Field(description="Null until Phase 2.")
    thumb_url: str | None
    created_at: datetime
    updated_at: datetime
    version: int


class IssuePage(Page[IssueListItem]):
    pass


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


class AllowedTransition(BaseModel):
    to_status: IssueStatus
    requires_reason: bool


class IssueDetail(IssueListItem):
    reports: list[ReportStaffView] = Field(description="Oldest first.")
    timeline: list[TimelineEvent] = Field(description="Oldest first.")
    allowed_transitions: list[AllowedTransition] = Field(
        description="What the caller may move this issue to right now."
    )


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


class IssueFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: uuid.UUID
    geometry: PointGeometry
    properties: IssueFeatureProperties


class IssueFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[IssueFeature]
    truncated: bool = Field(description="True when more issues matched than the cap returns.")
