"""The issue lifecycle states (PRD FR-052).

The set of states is fixed by the product; which moves between them are
allowed, and by whom, is per-tenant data in `status_transitions`.
"""

from __future__ import annotations

from enum import StrEnum


class IssueStatus(StrEnum):
    REPORTED = "reported"
    UNDER_REVIEW = "under_review"
    VERIFIED = "verified"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    PENDING_VERIFICATION = "pending_verification"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    CLOSED = "closed"
    REOPENED = "reopened"


def sql_in(values: type[StrEnum] | tuple[str, ...]) -> str:
    """`'a', 'b'` for CHECK constraints built from a vocabulary."""
    items = [v.value for v in values] if isinstance(values, type) else list(values)
    return ", ".join(f"'{item}'" for item in items)
