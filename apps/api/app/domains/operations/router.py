"""Phase 3 endpoints: assignment, notes, closure, verification, reopen,
workload (docs/api/phase-3-contract.md)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, status

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.storage import Storage
from app.domains.auth.dependencies import CurrentPrincipal
from app.domains.issues import service as issues
from app.domains.issues.schemas import IssueDetail, TimelineEvent
from app.domains.operations import bulk, closure, service
from app.domains.operations.schemas import (
    ApproveClosure,
    AssignmentCreate,
    AssignmentOut,
    NoteCreate,
    RejectClosure,
    ReopenRequest,
    VerificationCreate,
    Workload,
)
from app.domains.org.schemas import EligibleTeam
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.reports import service as reports
from app.domains.reports.schemas import ReportOwnerView

router = APIRouter(tags=["operations"])

Assigner = Annotated[Principal, require(Permission.ISSUE_READ, Permission.ISSUE_ASSIGN)]
Approver = Annotated[Principal, require(Permission.ISSUE_READ, Permission.ISSUE_APPROVE_CLOSURE)]
Editor = Annotated[Principal, require(Permission.ISSUE_READ, Permission.ISSUE_UPDATE)]
Reader = Annotated[Principal, require(Permission.ISSUE_READ)]
Verifier = Annotated[Principal, require(Permission.ISSUE_VERIFY)]


@router.get(
    "/issues/{issue_id}/eligible-teams",
    operation_id="issues_eligible_teams",
    response_model=list[EligibleTeam],
    responses=error_responses(401, 403, 404, 422),
)
async def eligible_teams(
    principal: Assigner, db: DbSession, issue_id: uuid.UUID
) -> list[EligibleTeam]:
    """Active teams that handle the issue's category and cover its ward,
    most local first."""
    return await service.eligible_teams(db, principal, issue_id)


@router.post(
    "/issues/{issue_id}/assignments",
    operation_id="issues_assign",
    response_model=IssueDetail,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def assign(
    principal: Assigner,
    db: DbSession,
    storage: Storage,
    issue_id: uuid.UUID,
    body: AssignmentCreate,
) -> IssueDetail:
    """Assign (from `verified` or `reopened`) or reassign (needs `reason`)
    to a team and optionally a member; a member gets a work order. Audited."""
    await service.assign(db, principal, issue_id, body)
    return await issues.get_detail(db, storage, principal, issue_id)


@router.get(
    "/issues/{issue_id}/assignments",
    operation_id="issues_assignment_history",
    response_model=list[AssignmentOut],
    responses=error_responses(401, 403, 404, 422),
)
async def assignment_history(
    principal: Reader, db: DbSession, issue_id: uuid.UUID
) -> list[AssignmentOut]:
    """Every assignment, newest first."""
    return await service.assignment_history(db, principal, issue_id)


@router.post(
    "/issues/{issue_id}/notes",
    operation_id="issues_add_note",
    response_model=TimelineEvent,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 404, 422),
)
async def add_note(
    principal: Editor, db: DbSession, issue_id: uuid.UUID, body: NoteCreate
) -> TimelineEvent:
    """An internal note (staff only) or a public update (shown to citizens)."""
    return await service.add_note(db, principal, issue_id, body)


@router.post(
    "/issues/{issue_id}/closure/approve",
    operation_id="issues_approve_closure",
    response_model=IssueDetail,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def approve_closure(
    principal: Approver, db: DbSession, storage: Storage, issue_id: uuid.UUID, body: ApproveClosure
) -> IssueDetail:
    """`pending_verification` → `resolved`; the resolution window starts."""
    await closure.approve(db, principal, issue_id, body)
    return await issues.get_detail(db, storage, principal, issue_id)


@router.post(
    "/issues/{issue_id}/closure/reject",
    operation_id="issues_reject_closure",
    response_model=IssueDetail,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def reject_closure(
    principal: Approver, db: DbSession, storage: Storage, issue_id: uuid.UUID, body: RejectClosure
) -> IssueDetail:
    """Back to `in_progress` with a reason; the work order resumes."""
    await closure.reject(db, principal, issue_id, body)
    return await issues.get_detail(db, storage, principal, issue_id)


@router.post(
    "/issues/{issue_id}/verification",
    operation_id="issues_verify",
    response_model=ReportOwnerView,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def verify(
    principal: Verifier,
    db: DbSession,
    storage: Storage,
    issue_id: uuid.UUID,
    body: VerificationCreate,
) -> ReportOwnerView:
    """A reporter says whether the issue is fixed. One answer per closure
    round. Returns the caller's report as they see it."""
    report_id = await closure.verify(db, principal, issue_id, body)
    view = await reports.get_owner_view(db, storage, report_id)
    assert view is not None
    return view


@router.post(
    "/issues/{issue_id}/reopen",
    operation_id="issues_reopen",
    response_model=IssueDetail | ReportOwnerView,
    responses=error_responses(401, 403, 404, 422),
)
async def reopen(
    principal: CurrentPrincipal,
    db: DbSession,
    storage: Storage,
    issue_id: uuid.UUID,
    body: ReopenRequest,
) -> IssueDetail | ReportOwnerView:
    """Reopen a `resolved` or `closed` issue. Staff get the issue detail; a
    reporter gets their report's owner view."""
    if await closure.reopen(db, principal, issue_id, body):
        return await issues.get_detail(db, storage, principal, issue_id)
    issue = await service.issue_for_citizen(db, issue_id)
    view = await reports.get_owner_view(
        db, storage, await closure.citizen_report_id(db, principal, issue)
    )
    assert view is not None
    return view


@router.get(
    "/workload",
    operation_id="workload_get",
    response_model=Workload,
    responses=error_responses(401, 403),
)
async def workload(principal: Assigner, db: DbSession) -> Workload:
    """Open work per team and member, for teams in the caller's scope."""
    return await service.workload(db, principal)


@router.post(
    "/issues/bulk",
    operation_id="issues_bulk",
    response_model=bulk.BulkResult,
    responses=error_responses(401, 403, 404, 422),
)
async def bulk_action(principal: Reader, db: DbSession, body: bulk.BulkAction) -> bulk.BulkResult:
    """Change the status of, or assign, up to 50 issues at once (FR-078).
    Each item carries the version the user saw and runs the single-issue
    action with its own checks; refused items are reported per item and
    don't undo the rest. Each change is audited, plus one summary event."""
    return await bulk.run(db, principal, body)
