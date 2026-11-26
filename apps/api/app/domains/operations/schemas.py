from __future__ import annotations

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.pagination import Page
from app.domains.categories.schemas import CategoryRef
from app.domains.issues.models import Visibility
from app.domains.media.models import MediaPhase
from app.domains.media.schemas import MediaOut
from app.domains.operations.models import (
    AssignmentEnd,
    ClosureState,
    VerificationOutcome,
    WorkOrderState,
)
from app.domains.org.schemas import TeamRef, UserRef
from app.domains.priority.rules import PriorityBand
from app.domains.reports.schemas import WardRef
from app.domains.workflow.statuses import IssueStatus


def _clean(value: str | None) -> str | None:
    return (value.strip() or None) if value is not None else None


def _required(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("This can't be blank.")
    return value


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LatLng(_Body):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


# --- assignment ------------------------------------------------------------------------------


class AssignmentCreate(_Body):
    team_id: uuid.UUID
    assignee_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(
        default=None, max_length=2000, description="Required when reassigning. Internal."
    )
    version: int = Field(ge=1, description="The issue's `version` you last saw.")

    _strip = field_validator("note", "reason")(_clean)


class WorkOrderRef(BaseModel):
    id: uuid.UUID
    state: WorkOrderState
    version: int


class AssignmentOut(BaseModel):
    id: uuid.UUID
    team: TeamRef
    assignee: UserRef | None
    note: str | None
    assigned_by: UserRef | None
    assigned_at: datetime
    ended_at: datetime | None
    end_reason: AssignmentEnd | None
    work_order: WorkOrderRef | None


class SceneMatch(BaseModel):
    """How alike the after photos and the citizens' photos look (FR-066).

    Advice for the supervisor only: a fixed pothole rightly looks different
    from the reported one, so nothing is decided from it (PRD §8.6)."""

    similarity: float = Field(
        ge=0,
        le=1,
        description="Best cosine similarity between any after photo and any report photo.",
    )
    model_id: str = Field(description="The vision model both photos were embedded with.")


class ClosureRequestOut(BaseModel):
    id: uuid.UUID
    state: ClosureState
    requested_by: UserRef | None
    requested_at: datetime
    reason_code: str | None
    note: str | None
    after_photos: list[MediaOut]
    requires_approval: bool
    confirmations: int
    unresolved: int
    scene_match: SceneMatch | None = Field(
        default=None,
        description=(
            "Null until the photos are analysed, with no after photo, or when "
            "the AI is unavailable."
        ),
    )


class OperationsOut(BaseModel):
    assignment: AssignmentOut | None = Field(description="The open assignment.")
    closure_request: ClosureRequestOut | None = Field(description="The pending closure request.")


# --- field -----------------------------------------------------------------------------------


class VersionBody(_Body):
    version: int = Field(ge=1, description="The work order's `version` you last saw.")


class DeclineBody(VersionBody):
    reason: str = Field(min_length=1, max_length=2000)

    _reason = field_validator("reason")(_required)


class ProgressBody(VersionBody):
    note: str | None = Field(default=None, max_length=2000)
    location: LatLng | None = None
    media_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)

    _strip = field_validator("note")(_clean)

    @model_validator(mode="after")
    def _something(self) -> Self:
        if not self.note and not self.media_ids:
            raise ValueError("Send a note or at least one photo.")
        if len(set(self.media_ids)) != len(self.media_ids):
            raise ValueError("Each photo can only be listed once.")
        return self


class ClosureRequestBody(VersionBody):
    media_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    reason_code: str | None = Field(default=None, max_length=50)
    note: str | None = Field(default=None, max_length=2000)

    _strip = field_validator("note", "reason_code")(_clean)

    @field_validator("media_ids")
    @classmethod
    def _unique(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Each photo can only be listed once.")
        return value


class FieldIssue(BaseModel):
    """What a field worker sees of the issue: no reporter data at all."""

    id: uuid.UUID
    reference: str
    status: IssueStatus
    category: CategoryRef
    location: LatLng
    address_text: str | None
    ward: WardRef | None
    priority_band: PriorityBand | None
    descriptions: list[str] = Field(description="Report descriptions, oldest first.")
    photos: list[MediaOut] = Field(description="Report photos (display and thumbnail copies).")


class EvidenceOut(MediaOut):
    phase: MediaPhase


class ProgressUpdateOut(BaseModel):
    at: datetime
    note: str | None
    location: LatLng | None


class FieldWorkOrder(BaseModel):
    id: uuid.UUID
    state: WorkOrderState
    version: int
    created_at: datetime
    updated_at: datetime
    issue: FieldIssue
    evidence: list[EvidenceOut]
    updates: list[ProgressUpdateOut] = Field(description="Oldest first.")


class FieldWorkOrderPage(Page[FieldWorkOrder]):
    pass


# --- notes, closure, verification ------------------------------------------------------------


class NoteCreate(_Body):
    body: str = Field(min_length=1, max_length=2000)
    visibility: Visibility

    _body = field_validator("body")(_required)


class ApproveClosure(_Body):
    version: int = Field(ge=1, description="The issue's `version` you last saw.")
    public_note: str | None = Field(default=None, max_length=2000)

    _strip = field_validator("public_note")(_clean)


class RejectClosure(_Body):
    version: int = Field(ge=1, description="The issue's `version` you last saw.")
    reason: str = Field(min_length=1, max_length=2000)

    _reason = field_validator("reason")(_required)


class VerificationCreate(_Body):
    outcome: VerificationOutcome
    note: str | None = Field(default=None, max_length=2000)

    _strip = field_validator("note")(_clean)


class ReopenRequest(_Body):
    reason: str = Field(min_length=1, max_length=2000)

    _reason = field_validator("reason")(_required)


# --- workload --------------------------------------------------------------------------------


class MemberLoad(BaseModel):
    user: UserRef
    open: int
    in_progress: int


class TeamLoad(BaseModel):
    team: TeamRef
    open: int
    pending_acceptance: int
    in_progress: int
    overdue: int = Field(description="Issues with open work here that are past their SLA.")
    members: list[MemberLoad]


class Workload(BaseModel):
    items: list[TeamLoad]
