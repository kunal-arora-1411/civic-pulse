"""When an issue counts as overdue or due soon (FR-057).

Kept free of service imports so the issue list, workload and analytics can
all share one definition.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import and_

from app.domains.issues.models import CivicIssue
from app.domains.workflow.statuses import IssueStatus

# The clock is paused in these states (see the `sla_schedule` trigger).
FINISHED = (IssueStatus.RESOLVED, IssueStatus.REJECTED, IssueStatus.CLOSED)
# "Due soon" once this share of the target time is left.
DUE_SOON_SHARE = 0.25


class SlaState(StrEnum):
    NONE = "none"  # no target applies, or the issue is finished
    ON_TRACK = "on_track"
    DUE_SOON = "due_soon"
    OVERDUE = "overdue"


def is_open(status: str) -> bool:
    return status not in FINISHED


def sla_state(issue: CivicIssue, now: datetime) -> SlaState:
    if issue.due_at is None or not is_open(issue.status):
        return SlaState.NONE
    if issue.due_at <= now:
        return SlaState.OVERDUE
    started = issue.sla_started_at or issue.created_at
    if (issue.due_at - now) <= (issue.due_at - started) * DUE_SOON_SHARE:
        return SlaState.DUE_SOON
    return SlaState.ON_TRACK


def overdue_clause(now: datetime) -> Any:
    """SQL: the issue is open and past its deadline."""
    return and_(
        CivicIssue.status.notin_([s.value for s in FINISHED]),
        CivicIssue.due_at.is_not(None),
        CivicIssue.due_at <= now,
    )
