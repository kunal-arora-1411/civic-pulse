from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Query

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.pagination import PageParamsDep
from app.core.storage import Storage
from app.domains.matching import review
from app.domains.matching.models import ReviewStatus
from app.domains.matching.schemas import (
    FeedbackIn,
    MatchDecisionOut,
    ResolveLink,
    ResolveNewIssue,
)
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal

router = APIRouter(tags=["matching"])

Triager = Annotated[Principal, require(Permission.ISSUE_TRIAGE)]


@router.get(
    "/review-tasks",
    operation_id="review_tasks_list",
    response_model=review.ReviewTaskPage,
    responses=error_responses(401, 403, 422),
)
async def list_review_tasks(
    principal: Triager,
    db: DbSession,
    storage: Storage,
    page: PageParamsDep,
    status: Annotated[
        ReviewStatus,
        Query(
            description="`open` (default, oldest first) or "
            "`resolved` (most recently resolved first)."
        ),
    ] = ReviewStatus.OPEN,
) -> review.ReviewTaskPage:
    """Ambiguous matches waiting for a person, within the caller's scope
    (by the report's ward)."""
    items, total = await review.list_tasks(db, storage, principal, page, status=status)
    return review.ReviewTaskPage(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/review-tasks/{task_id}",
    operation_id="review_tasks_get",
    response_model=review.ReviewTaskOut,
    responses=error_responses(401, 403, 404, 422),
)
async def get_review_task(
    principal: Triager, db: DbSession, storage: Storage, task_id: uuid.UUID
) -> review.ReviewTaskOut:
    return await review.get_task(db, storage, principal, task_id)


@router.post(
    "/review-tasks/{task_id}/resolve",
    operation_id="review_tasks_resolve",
    response_model=review.ReviewTaskOut,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def resolve_review_task(
    principal: Triager,
    db: DbSession,
    storage: Storage,
    task_id: uuid.UUID,
    body: Annotated[ResolveLink | ResolveNewIssue, Body(discriminator="action")],
) -> review.ReviewTaskOut:
    """`{"action": "link", "issue_id"}` links the report to one of the
    candidates (or to the issue it was merged into since); `{"action":
    "new_issue"}` starts a new issue. The chosen decision becomes
    `chosen_by_reviewer`, the rest `not_chosen`. Already resolved: `409`."""
    await review.resolve(db, principal, task_id, body)
    return await review.get_task(db, storage, principal, task_id)


@router.post(
    "/match-decisions/{decision_id}/feedback",
    operation_id="match_decisions_feedback",
    response_model=MatchDecisionOut,
    responses=error_responses(401, 403, 404, 422),
)
async def match_decision_feedback(
    principal: Triager, db: DbSession, decision_id: uuid.UUID, body: FeedbackIn
) -> MatchDecisionOut:
    """Mark a match as correct or incorrect (FR-035). Sending it again
    replaces the earlier feedback. Audited."""
    return await review.give_feedback(db, principal, decision_id, body)
