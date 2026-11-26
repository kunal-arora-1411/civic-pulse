"""Public resolution tracking (no login). Nothing here identifies a person:
no reporter names or contacts, no address text, no internal notes, only
face-blurred photo copies, and locations snapped to a coarse H3 cell."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.pagination import Page
from app.domains.categories.schemas import CategoryRef
from app.domains.issues.schemas import PointGeometry
from app.domains.reports.schemas import PublicTimelineEvent, WardRef
from app.domains.workflow.statuses import IssueStatus


class GeneralisedPoint(BaseModel):
    lat: float
    lng: float
    precision_m: int = Field(description="Roughly how far the real spot may be from this point.")


class PublicPhoto(BaseModel):
    thumb_url: str
    display_url: str


class PublicIssueItem(BaseModel):
    id: uuid.UUID
    reference: str
    status: IssueStatus
    category: CategoryRef
    ward: WardRef | None
    location: GeneralisedPoint = Field(description="The centre of the issue's H3 cell.")
    report_count: int
    support_count: int
    thumb_url: str | None = Field(description="A face-blurred thumbnail.")
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    age_days: float


class PublicIssuePage(Page[PublicIssueItem]):
    pass


class PublicIssueDetail(PublicIssueItem):
    timeline: list[PublicTimelineEvent] = Field(description="Public events, oldest first.")
    before_photos: list[PublicPhoto]
    after_photos: list[PublicPhoto]
    merged_into: str | None = Field(description="The reference this issue was merged into.")
    merged_into_id: uuid.UUID | None = Field(
        default=None, description="The id of that issue, for linking to its public page."
    )


class PublicFeatureProperties(BaseModel):
    id: uuid.UUID
    reference: str
    status: IssueStatus
    category_code: str
    report_count: int
    support_count: int


class PublicFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: uuid.UUID
    geometry: PointGeometry = Field(description="Generalised; coordinates are [lng, lat].")
    properties: PublicFeatureProperties


class PublicFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[PublicFeature]
    truncated: bool


class WardScore(BaseModel):
    ward: WardRef
    open_count: int
    resolved_count: int = Field(description="Resolved or closed.")
    median_resolution_days: float | None = Field(
        description="Median days from report to resolution; null when nothing is resolved."
    )


class Scorecard(BaseModel):
    wards: list[WardScore] = Field(description="Every ward, by name.")
