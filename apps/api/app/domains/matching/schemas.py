from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domains.matching.models import Decision, Feedback


class MatchSummary(BaseModel):
    """How matching placed a report (staff only)."""

    match_decision_id: uuid.UUID
    decision: Decision
    score: float
    signals: dict[str, Any] = Field(description="See the Phase 2 contract, D.3.")


class CandidateIssueRef(BaseModel):
    id: uuid.UUID
    reference: str


class DecisionActor(BaseModel):
    id: uuid.UUID
    display_name: str | None


class MatchDecisionOut(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    candidate_issue: CandidateIssueRef
    rank: int
    score: float
    signals: dict[str, Any]
    decision: Decision
    model_id: str | None
    decided_by: DecisionActor | None = Field(description="Null when the platform decided.")
    decided_at: datetime | None
    feedback: Feedback | None
    feedback_note: str | None
    feedback_at: datetime | None


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correct: bool
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None


class ResolveLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["link"]
    issue_id: uuid.UUID


class ResolveNewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["new_issue"]
