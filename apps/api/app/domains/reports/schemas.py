from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.core.pagination import Page
from app.domains.categories.models import MAX_PHOTOS_PER_REPORT
from app.domains.categories.schemas import CategoryRef
from app.domains.issues.models import EventType
from app.domains.media.schemas import MediaOut
from app.domains.reports.models import MAX_DESCRIPTION_LENGTH, LocationSource, ReportStatus
from app.domains.workflow.statuses import IssueStatus

# --- input -------------------------------------------------------------------------------


class LocationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100_000)
    source: LocationSource = Field(description="How the point was chosen (PRD §10.2).")


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: uuid.UUID
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    location: LocationIn
    address_text: str | None = Field(
        default=None, max_length=500, description="As confirmed by the citizen."
    )
    details: dict[str, Any] = Field(
        default_factory=dict, description="Answers to the category's `fields`."
    )
    media_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_PHOTOS_PER_REPORT)
    client_created_at: AwareDatetime | None = None

    @field_validator("description", "address_text")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("media_ids")
    @classmethod
    def _unique(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Each photo can only be attached once.")
        return value


# --- shared output pieces ------------------------------------------------------------------


class WardRef(BaseModel):
    id: uuid.UUID
    name: str


class LocationOut(BaseModel):
    lat: float
    lng: float
    accuracy_m: float | None
    source: LocationSource


class PublicTimelineEvent(BaseModel):
    """What a citizen may see of an issue's history: no notes marked
    internal, no reasons, no staff identities."""

    at: datetime
    type: EventType
    from_status: IssueStatus | None
    to_status: IssueStatus | None
    public_note: str | None


class IssueRef(BaseModel):
    id: uuid.UUID
    reference: str
    status: IssueStatus


class ReportIssue(IssueRef):
    timeline: list[PublicTimelineEvent]


class ReporterOut(BaseModel):
    id: uuid.UUID
    display_name: str | None


class ReporterWithContactOut(ReporterOut):
    """Only for callers holding `user:manage`."""

    phone: str
    email: str | None


class _ReportBase(BaseModel):
    id: uuid.UUID
    reference: str = Field(examples=["R-26-000123"])
    created_at: datetime
    category: CategoryRef
    description: str | None
    details: dict[str, Any]
    location: LocationOut
    address_text: str | None
    ward: WardRef | None
    media: list[MediaOut]
    status: ReportStatus


class ReportOwnerView(_ReportBase):
    """The reporter's own view."""

    view: Literal["owner"] = "owner"
    issue: ReportIssue | None


class ReportStaffView(_ReportBase):
    """What staff with `report:read` see. Contact details only with `user:manage`."""

    view: Literal["staff"] = "staff"
    reporter: ReporterWithContactOut | ReporterOut
    client_created_at: datetime | None
    issue: IssueRef | None


ReportView = Annotated[ReportOwnerView | ReportStaffView, Field(discriminator="view")]


class MyReportIssue(BaseModel):
    reference: str
    status: IssueStatus


class MyReportItem(BaseModel):
    id: uuid.UUID
    reference: str
    created_at: datetime
    category: CategoryRef
    thumb_url: str | None
    address_text: str | None
    issue: MyReportIssue | None


class MyReportPage(Page[MyReportItem]):
    pass
