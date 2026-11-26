"""Assignment, notes, workload, and the shared helpers that move an issue
through the platform's own (system-only) transitions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.errors import NotFound
from app.core.storage import ObjectStorage
from app.domains.audit import service as audit
from app.domains.categories.models import Category
from app.domains.categories.service import closure_policy
from app.domains.issues.errors import (
    InvalidTransition,
    IssueMerged,
    ReasonRequired,
    VersionConflict,
)
from app.domains.issues.models import CivicIssue, EventType, IssueEvent, Visibility
from app.domains.issues.schemas import EventActor, TimelineEvent
from app.domains.issues.service import get_in_scope
from app.domains.media.models import MediaAsset, MediaPhase
from app.domains.media.service import to_media_out
from app.domains.operations.errors import AssigneeNotInTeam, NotAssignable, TeamNotEligible
from app.domains.operations.models import (
    OPEN_WORK_ORDER_STATES,
    AssignmentEnd,
    ClosureRequest,
    ClosureState,
    IssueAssignment,
    IssueVerification,
    VerificationOutcome,
    WorkOrder,
    WorkOrderState,
)
from app.domains.operations.schemas import (
    AssignmentCreate,
    AssignmentOut,
    ClosureRequestOut,
    MemberLoad,
    NoteCreate,
    OperationsOut,
    TeamLoad,
    Workload,
    WorkOrderRef,
)
from app.domains.operations.states import Action, next_state
from app.domains.org import teams
from app.domains.org.models import Team, TeamCategory, TeamJurisdiction, TeamMember
from app.domains.org.schemas import TeamRef, UserRef
from app.domains.outbox.models import OutboxEvent
from app.domains.priority import service as priority
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.rbac.scope import accessible_jurisdiction_ids, jurisdiction_subtree
from app.domains.sla.rules import overdue_clause
from app.domains.users.models import User
from app.domains.workflow import service as workflow
from app.domains.workflow.statuses import IssueStatus as S

# --- shared helpers ------------------------------------------------------------------------


def check_version(issue: CivicIssue, version: int) -> None:
    if issue.merged_into_id is not None:
        raise IssueMerged(details={"merged_into": str(issue.merged_into_id)})
    if version != issue.version:
        raise VersionConflict(details={"version": issue.version})


def add_event(
    db: AsyncSession,
    issue: CivicIssue,
    type_: EventType,
    *,
    actor_id: uuid.UUID | None,
    visibility: Visibility,
    reason: str | None = None,
    public_note: str | None = None,
    data: dict[str, Any] | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
) -> IssueEvent:
    event = IssueEvent(
        tenant_id=issue.tenant_id,
        issue_id=issue.id,
        type=type_,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        public_note=public_note,
        visibility=visibility,
        actor_id=actor_id,
        data=data,
    )
    db.add(event)
    return event


async def move(
    db: AsyncSession,
    issue: CivicIssue,
    to_status: S,
    type_: EventType,
    *,
    actor_id: uuid.UUID | None,
    visibility: Visibility,
    reason: str | None = None,
    public_note: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    """Make one of the platform's own status moves, with its timeline event.

    The tenant's workflow must contain the move (a tenant that deleted it has
    turned that step off). The caller holds the issue's row lock. Bumps the
    version and recomputes priority, like a staff status change.
    """
    from_status = issue.status
    if not await workflow.has_transition(db, from_status, to_status.value):
        raise InvalidTransition(details={"from_status": from_status, "to_status": to_status.value})
    now = datetime.now(UTC)
    issue.status = to_status.value
    issue.status_changed_at = now
    if to_status == S.RESOLVED:
        issue.resolved_at = now
    issue.version += 1
    add_event(
        db,
        issue,
        type_,
        actor_id=actor_id,
        visibility=visibility,
        reason=reason,
        public_note=public_note,
        data=data,
        from_status=from_status,
        to_status=to_status.value,
    )
    await db.flush()
    await priority.recompute(db, issue.id)


def advance(work_order: WorkOrder, action: Action) -> None:
    """Apply a work-order action whose validity the caller already checked
    (or that the issue's state guarantees)."""
    target = next_state(WorkOrderState(work_order.state), action)
    if target is None:  # a bug, not a user error: the issue and order disagree
        raise InvalidTransition(details={"work_order_state": work_order.state, "action": action})
    work_order.state = target.value
    work_order.version += 1


async def open_assignment(db: AsyncSession, issue_id: uuid.UUID) -> IssueAssignment | None:
    return await db.scalar(
        select(IssueAssignment)
        .where(IssueAssignment.issue_id == issue_id, IssueAssignment.ended_at.is_(None))
        .with_for_update()
    )


async def open_work_order(db: AsyncSession, issue_id: uuid.UUID) -> WorkOrder | None:
    return await db.scalar(
        select(WorkOrder)
        .where(WorkOrder.issue_id == issue_id, WorkOrder.state.in_(OPEN_WORK_ORDER_STATES))
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def end_assignment(assignment: IssueAssignment, reason: AssignmentEnd) -> None:
    assignment.ended_at = datetime.now(UTC)
    assignment.end_reason = reason.value


# --- assignment (FR-062) ---------------------------------------------------------------------

ASSIGNABLE = (S.VERIFIED, S.REOPENED)
REASSIGNABLE = (S.ASSIGNED, S.IN_PROGRESS)


async def assign(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID, body: AssignmentCreate
) -> None:
    issue = await get_in_scope(
        db, principal, issue_id, for_update=True, permission=Permission.ISSUE_ASSIGN
    )
    check_version(issue, body.version)
    current = await open_assignment(db, issue.id)
    if issue.status not in (*ASSIGNABLE, *REASSIGNABLE):
        raise NotAssignable(details={"status": issue.status})
    # A reopened issue may still hold the assignment that resolved it; a new
    # assignment simply replaces it. Only taking work away mid-flight is a
    # reassignment that needs a reason.
    reassigning = current is not None and issue.status in REASSIGNABLE
    if current is not None and not reassigning:
        end_assignment(current, AssignmentEnd.REASSIGNED)
        await db.flush()
        current = None
    if reassigning and not body.reason:
        raise ReasonRequired(details={"action": "reassign"})

    team = await db.scalar(select(Team).where(Team.id == body.team_id))
    if team is None or not team.is_active:
        raise TeamNotEligible(details={"reason": "inactive"})
    if team.id not in await teams.coverage_depth(db, issue.category_id, issue.ward_id):
        handles = await db.scalar(
            select(TeamCategory.team_id).where(
                TeamCategory.team_id == team.id, TeamCategory.category_id == issue.category_id
            )
        )
        raise TeamNotEligible(details={"reason": "area" if handles else "category"})
    assignee: User | None = None
    if body.assignee_id is not None:
        assignee = await db.scalar(
            select(User)
            .join(TeamMember, TeamMember.user_id == User.id)
            .where(TeamMember.team_id == team.id, User.id == body.assignee_id)
        )
        if assignee is None or not assignee.is_active:
            raise AssigneeNotInTeam(details={"assignee_id": str(body.assignee_id)})

    previous: dict[str, Any] = {}
    if current is not None:
        previous = {
            "previous_team_id": str(current.team_id),
            "previous_assignee_id": str(current.assignee_id) if current.assignee_id else None,
        }
        end_assignment(current, AssignmentEnd.REASSIGNED)
        old_order = await open_work_order(db, issue.id)
        if old_order is not None:
            advance(old_order, Action.CANCEL)
        await db.flush()

    assignment = IssueAssignment(
        tenant_id=issue.tenant_id,
        issue_id=issue.id,
        team_id=team.id,
        assignee_id=body.assignee_id,
        note=body.note,
        assigned_by=principal.user_id,
    )
    db.add(assignment)
    await db.flush()
    work_order: WorkOrder | None = None
    if assignee is not None:
        work_order = WorkOrder(
            tenant_id=issue.tenant_id,
            issue_id=issue.id,
            assignment_id=assignment.id,
            assignee_id=assignee.id,
            state=WorkOrderState.PENDING_ACCEPTANCE,
        )
        db.add(work_order)
        await db.flush()

    data = {
        "team": {"id": str(team.id), "name": team.name},
        "assignee": {"id": str(assignee.id), "display_name": assignee.display_name}
        if assignee
        else None,
        "note": body.note,
        "work_order_id": str(work_order.id) if work_order else None,
        **previous,
    }
    if issue.status in ASSIGNABLE or issue.status == S.IN_PROGRESS:
        # First assignment is public; moving an in-progress issue back to
        # `assigned` on reassignment is a staff matter.
        await move(
            db,
            issue,
            S.ASSIGNED,
            EventType.REASSIGNED if reassigning else EventType.ASSIGNED,
            actor_id=principal.user_id,
            visibility=Visibility.INTERNAL if reassigning else Visibility.PUBLIC,
            reason=body.reason,
            data=data,
        )
    else:
        issue.version += 1
        add_event(
            db,
            issue,
            EventType.REASSIGNED,
            actor_id=principal.user_id,
            visibility=Visibility.INTERNAL,
            reason=body.reason,
            data=data,
        )
    db.add(
        OutboxEvent(
            tenant_id=issue.tenant_id,
            event_type="issue.assigned",
            aggregate_type="issue",
            aggregate_id=issue.id,
            payload={
                "issue_id": str(issue.id),
                "assignment_id": str(assignment.id),
                "team_id": str(team.id),
                "assignee_id": str(assignee.id) if assignee else None,
                "work_order_id": str(work_order.id) if work_order else None,
                "reassigned": reassigning,
            },
        )
    )
    await db.flush()
    await audit.record(
        db,
        action="issue.reassigned" if reassigning else "issue.assigned",
        entity_type="issue",
        entity_id=issue.id,
        actor=principal,
        after={**data, "reason": body.reason, "version": issue.version},
    )


async def eligible_teams(db: AsyncSession, principal: Principal, issue_id: uuid.UUID):
    issue = await get_in_scope(db, principal, issue_id, permission=Permission.ISSUE_ASSIGN)
    return await teams.eligible_teams(db, issue.category_id, issue.ward_id)


_assignee = aliased(User)
_assigner = aliased(User)


async def _assignment_views(
    db: AsyncSession, issue_id: uuid.UUID, *, open_only: bool = False
) -> list[AssignmentOut]:
    stmt = (
        select(IssueAssignment, Team.name, _assignee.display_name, _assigner.display_name)
        .join(Team, Team.id == IssueAssignment.team_id)
        .outerjoin(_assignee, _assignee.id == IssueAssignment.assignee_id)
        .outerjoin(_assigner, _assigner.id == IssueAssignment.assigned_by)
        .where(IssueAssignment.issue_id == issue_id)
        .order_by(IssueAssignment.created_at.desc(), IssueAssignment.id)
    )
    if open_only:
        stmt = stmt.where(IssueAssignment.ended_at.is_(None))
    rows = (await db.execute(stmt)).all()
    orders = {
        wo.assignment_id: wo
        for wo in await db.scalars(
            select(WorkOrder).where(WorkOrder.assignment_id.in_([r[0].id for r in rows]))
        )
    }
    out: list[AssignmentOut] = []
    for a, team_name, assignee_name, assigner_name in rows:
        wo = orders.get(a.id)
        out.append(
            AssignmentOut(
                id=a.id,
                team=TeamRef(id=a.team_id, name=team_name),
                assignee=UserRef(id=a.assignee_id, display_name=assignee_name)
                if a.assignee_id
                else None,
                note=a.note,
                assigned_by=UserRef(id=a.assigned_by, display_name=assigner_name)
                if a.assigned_by
                else None,
                assigned_at=a.created_at,
                ended_at=a.ended_at,
                end_reason=AssignmentEnd(a.end_reason) if a.end_reason else None,
                work_order=WorkOrderRef(
                    id=wo.id, state=WorkOrderState(wo.state), version=wo.version
                )
                if wo
                else None,
            )
        )
    return out


async def assignment_history(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID
) -> list[AssignmentOut]:
    issue = await get_in_scope(db, principal, issue_id)
    return await _assignment_views(db, issue.id)


async def closure_view(
    db: AsyncSession, storage: ObjectStorage, issue: CivicIssue
) -> ClosureRequestOut | None:
    request = await db.scalar(
        select(ClosureRequest).where(
            ClosureRequest.issue_id == issue.id, ClosureRequest.state == ClosureState.PENDING
        )
    )
    if request is None:
        return None
    requester = (
        await db.scalar(select(User.display_name).where(User.id == request.requested_by))
        if request.requested_by
        else None
    )
    photos: list[MediaAsset] = []
    if request.work_order_id is not None:
        photos = list(
            await db.scalars(
                select(MediaAsset)
                .where(
                    MediaAsset.work_order_id == request.work_order_id,
                    MediaAsset.phase == MediaPhase.AFTER,
                )
                .order_by(MediaAsset.created_at, MediaAsset.id)
            )
        )
    counts = dict(
        (
            await db.execute(
                select(IssueVerification.outcome, func.count())
                .where(IssueVerification.closure_request_id == request.id)
                .group_by(IssueVerification.outcome)
            )
        ).all()
    )
    category = await db.scalar(select(Category).where(Category.id == issue.category_id))
    assert category is not None
    return ClosureRequestOut(
        id=request.id,
        state=ClosureState(request.state),
        requested_by=UserRef(id=request.requested_by, display_name=requester)
        if request.requested_by
        else None,
        requested_at=request.created_at,
        reason_code=request.reason_code,
        note=request.note,
        after_photos=[to_media_out(storage, m, staff=True) for m in photos],
        requires_approval=closure_policy(category).requires_approval,
        confirmations=counts.get(VerificationOutcome.RESOLVED, 0),
        unresolved=counts.get(VerificationOutcome.UNRESOLVED, 0),
    )


async def operations_view(
    db: AsyncSession, storage: ObjectStorage, issue: CivicIssue
) -> OperationsOut:
    open_ = await _assignment_views(db, issue.id, open_only=True)
    return OperationsOut(
        assignment=open_[0] if open_ else None,
        closure_request=await closure_view(db, storage, issue),
    )


# --- notes (FR-067) --------------------------------------------------------------------------


async def add_note(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID, body: NoteCreate
) -> TimelineEvent:
    issue = await get_in_scope(
        db, principal, issue_id, for_update=True, permission=Permission.ISSUE_UPDATE
    )
    public = body.visibility == Visibility.PUBLIC
    event = add_event(
        db,
        issue,
        EventType.NOTE,
        actor_id=principal.user_id,
        visibility=body.visibility,
        public_note=body.body if public else None,
        reason=None if public else body.body,
    )
    await db.flush()
    await db.refresh(event, ["created_at"])
    name = await db.scalar(select(User.display_name).where(User.id == principal.user_id))
    await audit.record(
        db,
        action="issue.note_added",
        entity_type="issue",
        entity_id=issue.id,
        actor=principal,
        after={"visibility": body.visibility.value, "event_id": str(event.id)},
    )
    return TimelineEvent(
        id=event.id,
        at=event.created_at,
        type=EventType.NOTE,
        from_status=None,
        to_status=None,
        reason=event.reason,
        public_note=event.public_note,
        visibility=body.visibility,
        actor=EventActor(id=principal.user_id, display_name=name),
        related_issue=None,
        data=None,
    )


# --- workload (FR-068) -----------------------------------------------------------------------


async def workload(db: AsyncSession, principal: Principal) -> Workload:
    """Teams whose service area overlaps the caller's `issue:assign` scope."""
    scope = await accessible_jurisdiction_ids(db, principal, Permission.ISSUE_ASSIGN)
    stmt = select(Team).where(Team.is_active.is_(True)).order_by(Team.name, Team.id)
    if scope is not None:
        # A team overlaps when one of its jurisdictions is inside the scope
        # or contains part of it (a city-wide team for a ward supervisor).
        team_ids: set[uuid.UUID] = set()
        for team_id, jurisdiction_id in await db.execute(
            select(TeamJurisdiction.team_id, TeamJurisdiction.jurisdiction_id)
        ):
            if jurisdiction_id in scope or (
                await jurisdiction_subtree(db, [jurisdiction_id]) & scope
            ):
                team_ids.add(team_id)
        stmt = stmt.where(Team.id.in_(team_ids))
    team_rows = list(await db.scalars(stmt))
    if not team_rows:
        return Workload(items=[])

    counts = (
        await db.execute(
            select(IssueAssignment.team_id, WorkOrder.assignee_id, WorkOrder.state, func.count())
            .join(IssueAssignment, IssueAssignment.id == WorkOrder.assignment_id)
            .where(
                IssueAssignment.team_id.in_([t.id for t in team_rows]),
                WorkOrder.state.in_(OPEN_WORK_ORDER_STATES),
            )
            .group_by(IssueAssignment.team_id, WorkOrder.assignee_id, WorkOrder.state)
        )
    ).all()
    overdue: dict[uuid.UUID, int] = dict(
        (
            await db.execute(
                select(IssueAssignment.team_id, func.count(func.distinct(CivicIssue.id)))
                .join(WorkOrder, WorkOrder.assignment_id == IssueAssignment.id)
                .join(CivicIssue, CivicIssue.id == IssueAssignment.issue_id)
                .where(
                    IssueAssignment.team_id.in_([t.id for t in team_rows]),
                    WorkOrder.state.in_(OPEN_WORK_ORDER_STATES),
                    overdue_clause(datetime.now(UTC)),
                )
                .group_by(IssueAssignment.team_id)
            )
        ).all()
    )
    members = (
        await db.execute(
            select(TeamMember.team_id, User.id, User.display_name)
            .join(User, User.id == TeamMember.user_id)
            .where(TeamMember.team_id.in_([t.id for t in team_rows]))
            .order_by(User.display_name, User.id)
        )
    ).all()

    items: list[TeamLoad] = []
    for team in team_rows:
        rows = [c for c in counts if c[0] == team.id]

        def total(
            *states: WorkOrderState,
            user: uuid.UUID | None = None,
            rows: list[Any] = rows,
        ) -> int:
            return sum(
                n for _, uid, state, n in rows if state in states and (user is None or uid == user)
            )

        items.append(
            TeamLoad(
                team=TeamRef(id=team.id, name=team.name),
                open=total(*OPEN_WORK_ORDER_STATES),
                pending_acceptance=total(WorkOrderState.PENDING_ACCEPTANCE),
                in_progress=total(WorkOrderState.IN_PROGRESS),
                overdue=overdue.get(team.id, 0),
                members=[
                    MemberLoad(
                        user=UserRef(id=uid, display_name=name),
                        open=total(*OPEN_WORK_ORDER_STATES, user=uid),
                        in_progress=total(WorkOrderState.IN_PROGRESS, user=uid),
                    )
                    for tid, uid, name in members
                    if tid == team.id
                ],
            )
        )
    return Workload(items=items)


async def issue_for_citizen(db: AsyncSession, issue_id: uuid.UUID) -> CivicIssue:
    issue = await db.scalar(
        select(CivicIssue)
        .where(CivicIssue.id == issue_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if issue is None:
        raise NotFound()
    return issue
