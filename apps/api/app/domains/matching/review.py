"""The human review queue (FR-031, FR-035, FR-037) and match feedback.

Review tasks and match decisions are scoped by the report's ward, with the
caller's `issue:triage` grants: out of scope answers 404, as everywhere.
Resolving takes the same family lock as matching, then the task's row
lock: of two operators resolving one task at once, the second waits and
then finds it resolved (409).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import Page, PageParams, paginate
from app.core.storage import ObjectStorage
from app.domains.audit import service as audit
from app.domains.issues import service as issues
from app.domains.issues.models import CivicIssue
from app.domains.issues.schemas import IssueListItem
from app.domains.matching import linking
from app.domains.matching.models import (
    Decision,
    Feedback,
    MatchDecision,
    ReviewResolution,
    ReviewStatus,
    ReviewTask,
)
from app.domains.matching.schemas import (
    FeedbackIn,
    MatchDecisionOut,
    ResolveLink,
    ResolveNewIssue,
)
from app.domains.matching.views import to_out
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.rbac.scope import accessible_jurisdiction_ids, scope_filter
from app.domains.reports import service as reports
from app.domains.reports.models import Report
from app.domains.reports.schemas import ReportStaffView
from app.domains.users.models import User


class ReviewCandidate(BaseModel):
    match_decision_id: uuid.UUID
    score: float
    signals: dict[str, Any]
    decision: Decision
    issue: IssueListItem


class ReviewActor(BaseModel):
    id: uuid.UUID
    display_name: str | None


class ReviewTaskOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    status: ReviewStatus
    resolution: ReviewResolution | None
    resolved_issue_id: uuid.UUID | None
    resolved_by: ReviewActor | None
    resolved_at: datetime | None
    report: ReportStaffView
    candidates: list[ReviewCandidate] = Field(
        description="Best first. Candidates outside the caller's scope are left out."
    )


class ReviewTaskPage(Page[ReviewTaskOut]):
    pass


async def _scope(db: AsyncSession, principal: Principal) -> set[uuid.UUID] | None:
    return await accessible_jurisdiction_ids(db, principal, Permission.ISSUE_TRIAGE)


async def _views(
    db: AsyncSession, storage: ObjectStorage, principal: Principal, tasks: list[ReviewTask]
) -> list[ReviewTaskOut]:
    if not tasks:
        return []
    report_ids = [t.report_id for t in tasks]
    rows = await reports.fetch_report_rows(db, Report.id.in_(report_ids))
    staff = await reports.staff_views(
        db, storage, rows, with_contact=principal.has(Permission.USER_MANAGE)
    )
    by_report = {view.id: view for view in staff}
    decisions = (
        await db.scalars(
            select(MatchDecision)
            .where(MatchDecision.report_id.in_(report_ids))
            .order_by(MatchDecision.report_id, MatchDecision.rank)
        )
    ).all()
    items = await issues.list_items(
        db, storage, principal, list({d.candidate_issue_id for d in decisions})
    )
    resolver_ids = [t.resolved_by for t in tasks if t.resolved_by]
    names = await db.execute(select(User.id, User.display_name).where(User.id.in_(resolver_ids)))
    resolvers: dict[uuid.UUID, str | None] = {row[0]: row[1] for row in names.all()}
    out = []
    for task in tasks:
        candidates = [
            ReviewCandidate(
                match_decision_id=d.id,
                score=d.score,
                signals=d.signals,
                decision=Decision(d.decision),
                issue=items[d.candidate_issue_id],
            )
            for d in decisions
            if d.report_id == task.report_id and d.candidate_issue_id in items
        ]
        out.append(
            ReviewTaskOut(
                id=task.id,
                created_at=task.created_at,
                status=ReviewStatus(task.status),
                resolution=ReviewResolution(task.resolution) if task.resolution else None,
                resolved_issue_id=task.resolved_issue_id,
                resolved_by=ReviewActor(
                    id=task.resolved_by, display_name=resolvers.get(task.resolved_by)
                )
                if task.resolved_by
                else None,
                resolved_at=task.resolved_at,
                report=by_report[task.report_id],
                candidates=candidates,
            )
        )
    return out


async def list_tasks(
    db: AsyncSession,
    storage: ObjectStorage,
    principal: Principal,
    params: PageParams,
    *,
    status: ReviewStatus,
) -> tuple[list[ReviewTaskOut], int]:
    scope = await _scope(db, principal)
    stmt = (
        select(ReviewTask)
        .join(Report, Report.id == ReviewTask.report_id)
        .where(
            ReviewTask.tenant_id == principal.tenant_id,
            ReviewTask.status == status,
            scope_filter(Report.ward_id, scope),
        )
    )
    if status is ReviewStatus.OPEN:  # a queue: oldest first
        stmt = stmt.order_by(ReviewTask.created_at, ReviewTask.id)
    else:
        stmt = stmt.order_by(ReviewTask.resolved_at.desc(), ReviewTask.id.desc())
    rows, total = await paginate(db, stmt, params)
    return await _views(db, storage, principal, [row[0] for row in rows]), total


async def _task_in_scope(
    db: AsyncSession, principal: Principal, task_id: uuid.UUID
) -> tuple[ReviewTask, Report]:
    row = (
        await db.execute(
            select(ReviewTask, Report)
            .join(Report, Report.id == ReviewTask.report_id)
            .where(ReviewTask.id == task_id)
        )
    ).one_or_none()
    if row is None or not reports.in_scope(await _scope(db, principal), row[1].ward_id):
        raise NotFound()
    return row[0], row[1]


async def get_task(
    db: AsyncSession, storage: ObjectStorage, principal: Principal, task_id: uuid.UUID
) -> ReviewTaskOut:
    task, _ = await _task_in_scope(db, principal, task_id)
    (view,) = await _views(db, storage, principal, [task])
    return view


async def _survivor(db: AsyncSession, issue_id: uuid.UUID) -> CivicIssue:
    """The issue a candidate now lives on: itself, or what it was merged into."""
    issue = await db.get(CivicIssue, issue_id)
    seen: set[uuid.UUID] = set()
    while issue is not None and issue.merged_into_id is not None and issue.id not in seen:
        seen.add(issue.id)
        issue = await db.get(CivicIssue, issue.merged_into_id)
    if issue is None or issue.merged_into_id is not None:
        raise Conflict("The chosen issue no longer exists as it was. Reload and try again.")
    return issue


async def resolve(
    db: AsyncSession,
    principal: Principal,
    task_id: uuid.UUID,
    body: ResolveLink | ResolveNewIssue,
) -> None:
    task, report = await _task_in_scope(db, principal, task_id)
    decisions = (
        await db.scalars(select(MatchDecision).where(MatchDecision.report_id == report.id))
    ).all()
    chosen: MatchDecision | None = None
    target: CivicIssue | None = None
    families = [report.category_id]
    if isinstance(body, ResolveLink):
        chosen = next((d for d in decisions if d.candidate_issue_id == body.issue_id), None)
        if chosen is None:
            raise ValidationFailed(
                "That issue isn't one of this task's candidates.",
                details={
                    "errors": [
                        {
                            "loc": ["body", "issue_id"],
                            "msg": "Not a candidate for this report.",
                            "type": "invalid_value",
                        }
                    ]
                },
            )
        target = await _survivor(db, body.issue_id)
        families.append(target.category_id)

    # Same order as matching: family locks, then the task, report and issue rows.
    await linking.lock_families(db, report.tenant_id, families)
    task = await db.scalar(
        select(ReviewTask)
        .where(ReviewTask.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert task is not None
    if task.status != ReviewStatus.OPEN:
        raise Conflict("This review task was already resolved.", details={"status": task.status})
    report = await db.scalar(
        select(Report)
        .where(Report.id == report.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert report is not None
    now = datetime.now(UTC)

    if target is not None:
        locked = (await linking.lock_issues(db, [target.id]))[target.id]
        if locked.merged_into_id is not None:
            raise Conflict("The chosen issue was just merged. Reload and try again.")
        await linking.link_report(db, report, locked, actor=principal, reason="review")
        resolution, issue_id = ReviewResolution.LINKED, locked.id
    else:
        issue = await linking.create_issue_for_report(db, report, actor=principal, reason="review")
        resolution, issue_id = ReviewResolution.NEW_ISSUE, issue.id

    for decision in decisions:
        decision.decision = (
            Decision.CHOSEN_BY_REVIEWER if decision is chosen else Decision.NOT_CHOSEN
        )
        decision.decided_by = principal.user_id
        decision.decided_at = now
    task.status = ReviewStatus.RESOLVED
    task.resolution = resolution
    task.resolved_issue_id = issue_id
    task.resolved_by = principal.user_id
    task.resolved_at = now
    await db.flush()
    await audit.record(
        db,
        action="review_task.resolved",
        entity_type="review_task",
        entity_id=task.id,
        actor=principal,
        after={
            "report_id": str(report.id),
            "resolution": resolution.value,
            "issue_id": str(issue_id),
            "chosen_candidate": str(chosen.candidate_issue_id) if chosen else None,
        },
    )


async def give_feedback(
    db: AsyncSession, principal: Principal, decision_id: uuid.UUID, body: FeedbackIn
) -> MatchDecisionOut:
    row = (
        await db.execute(
            select(MatchDecision, Report.ward_id)
            .join(Report, Report.id == MatchDecision.report_id)
            .where(MatchDecision.id == decision_id)
        )
    ).one_or_none()
    if row is None or not reports.in_scope(await _scope(db, principal), row[1]):
        raise NotFound()
    decision = await db.scalar(
        select(MatchDecision)
        .where(MatchDecision.id == decision_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert decision is not None
    before = {"feedback": decision.feedback, "note": decision.feedback_note}
    decision.feedback = Feedback.CORRECT if body.correct else Feedback.INCORRECT
    decision.feedback_note = body.note
    decision.feedback_by = principal.user_id
    decision.feedback_at = datetime.now(UTC)
    await db.flush()
    await audit.record(
        db,
        action="match_decision.feedback",
        entity_type="match_decision",
        entity_id=decision.id,
        actor=principal,
        before=before,
        after={
            "feedback": decision.feedback,
            "note": decision.feedback_note,
            "decision": decision.decision,
            "report_id": str(decision.report_id),
        },
    )
    reference = await db.scalar(
        select(CivicIssue.reference).where(CivicIssue.id == decision.candidate_issue_id)
    )
    decider = (
        await db.scalar(select(User.display_name).where(User.id == decision.decided_by))
        if decision.decided_by
        else None
    )
    return to_out(decision, reference or "", decider)
