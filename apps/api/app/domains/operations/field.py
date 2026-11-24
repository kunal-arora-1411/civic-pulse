"""The field worker's side: their queue, a work order, and its actions
(FR-063 to FR-066, FR-070).

Every query is scoped to `assignee_id = caller`: anyone else's work order
is a 404. Views are built from field schemas that have no reporter fields.
Locks are taken issue first, then work order, the same order assignment
uses, so the two can't deadlock.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.pagination import PageParams, paginate
from app.core.storage import ObjectStorage
from app.domains.audit import service as audit
from app.domains.categories.models import Category
from app.domains.categories.service import closure_policy, to_ref
from app.domains.issues.models import CivicIssue, EventType, IssueEvent, Visibility
from app.domains.issues.service import EFFECTIVE_BAND
from app.domains.media.models import MediaAsset, MediaPhase, MediaPurpose, MediaStatus
from app.domains.media.service import to_media_out
from app.domains.operations.errors import (
    ClosureEvidenceRequired,
    InvalidWorkOrderAction,
    WorkOrderConflict,
)
from app.domains.operations.models import (
    AssignmentEnd,
    ClosureRequest,
    IssueAssignment,
    WorkOrder,
    WorkOrderState,
)
from app.domains.operations.schemas import (
    ClosureRequestBody,
    DeclineBody,
    EvidenceOut,
    FieldIssue,
    FieldWorkOrder,
    LatLng,
    ProgressBody,
    ProgressUpdateOut,
    VersionBody,
)
from app.domains.operations.service import add_event, end_assignment, move
from app.domains.operations.states import Action, next_state
from app.domains.org.models import Jurisdiction
from app.domains.priority.rules import PriorityBand
from app.domains.rbac.principal import Principal
from app.domains.reports.errors import InvalidMedia
from app.domains.reports.models import Report, ReportStatus
from app.domains.reports.schemas import WardRef
from app.domains.reports.service import media_for_reports
from app.domains.workflow.statuses import IssueStatus as S

DEFAULT_STATES = tuple(
    s for s in WorkOrderState if s not in (WorkOrderState.DECLINED, WorkOrderState.CANCELLED)
)
_USABLE = (MediaStatus.PROCESSING, MediaStatus.READY)


# --- views -----------------------------------------------------------------------------------


async def _views(
    db: AsyncSession, storage: ObjectStorage, orders: Sequence[WorkOrder]
) -> list[FieldWorkOrder]:
    if not orders:
        return []
    issue_ids = list({wo.issue_id for wo in orders})
    issues = {
        row[0].id: row
        for row in await db.execute(
            select(
                CivicIssue,
                func.ST_X(CivicIssue.location),
                func.ST_Y(CivicIssue.location),
                Category,
                Jurisdiction.name,
                EFFECTIVE_BAND,
            )
            .join(Category, Category.id == CivicIssue.category_id)
            .outerjoin(Jurisdiction, Jurisdiction.id == CivicIssue.ward_id)
            .where(CivicIssue.id.in_(issue_ids))
        )
    }
    reports: dict[uuid.UUID, list[tuple[uuid.UUID, str | None]]] = defaultdict(list)
    for issue_id, report_id, description in await db.execute(
        select(Report.issue_id, Report.id, Report.description)
        .where(Report.issue_id.in_(issue_ids), Report.status == ReportStatus.ACCEPTED)
        .order_by(Report.created_at, Report.id)
    ):
        assert issue_id is not None
        reports[issue_id].append((report_id, description))
    media = await media_for_reports(db, [r for rs in reports.values() for r, _ in rs])
    evidence: dict[uuid.UUID, list[MediaAsset]] = defaultdict(list)
    for asset in await db.scalars(
        select(MediaAsset)
        .where(MediaAsset.work_order_id.in_([wo.id for wo in orders]))
        .order_by(MediaAsset.created_at, MediaAsset.id)
    ):
        assert asset.work_order_id is not None
        evidence[asset.work_order_id].append(asset)
    updates: dict[uuid.UUID, list[ProgressUpdateOut]] = defaultdict(list)
    for event in await db.scalars(
        select(IssueEvent)
        .where(IssueEvent.issue_id.in_(issue_ids), IssueEvent.type == EventType.PROGRESS)
        .order_by(IssueEvent.created_at, IssueEvent.id)
    ):
        data = event.data or {}
        loc = data.get("location")
        updates[uuid.UUID(data["work_order_id"])].append(
            ProgressUpdateOut(
                at=event.created_at,
                note=data.get("note"),
                location=LatLng(**loc) if loc else None,
            )
        )

    out: list[FieldWorkOrder] = []
    for wo in orders:
        issue, x, y, category, ward_name, band = issues[wo.issue_id]
        issue_reports = reports[wo.issue_id]
        out.append(
            FieldWorkOrder(
                id=wo.id,
                state=WorkOrderState(wo.state),
                version=wo.version,
                created_at=wo.created_at,
                updated_at=wo.updated_at,
                issue=FieldIssue(
                    id=issue.id,
                    reference=issue.reference,
                    status=S(issue.status),
                    category=to_ref(category),
                    location=LatLng(lat=float(y), lng=float(x)),
                    address_text=issue.address_text,
                    ward=WardRef(id=issue.ward_id, name=ward_name)
                    if issue.ward_id and ward_name
                    else None,
                    priority_band=PriorityBand(band) if band else None,
                    descriptions=[d for _, d in issue_reports if d],
                    photos=[
                        to_media_out(storage, m, staff=False)
                        for r, _ in issue_reports
                        for m in media[r]
                    ],
                ),
                evidence=[
                    EvidenceOut(
                        **to_media_out(storage, m, staff=False).model_dump(),
                        phase=MediaPhase(m.phase),
                    )
                    for m in evidence[wo.id]
                ],
                updates=updates[wo.id],
            )
        )
    return out


async def list_mine(
    db: AsyncSession,
    storage: ObjectStorage,
    principal: Principal,
    params: PageParams,
    states: list[WorkOrderState] | None,
) -> tuple[list[FieldWorkOrder], int]:
    stmt = (
        select(WorkOrder)
        .where(
            WorkOrder.assignee_id == principal.user_id,
            WorkOrder.state.in_([s.value for s in (states or DEFAULT_STATES)]),
        )
        .order_by(WorkOrder.created_at.desc(), WorkOrder.id.desc())
    )
    rows, total = await paginate(db, stmt, params)
    return await _views(db, storage, [r[0] for r in rows]), total


async def _mine(
    db: AsyncSession, principal: Principal, work_order_id: uuid.UUID, *, lock: bool = False
) -> WorkOrder:
    stmt = select(WorkOrder).where(
        WorkOrder.id == work_order_id, WorkOrder.assignee_id == principal.user_id
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    work_order = await db.scalar(stmt)
    if work_order is None:
        raise NotFound()
    return work_order


async def get_mine(
    db: AsyncSession, storage: ObjectStorage, principal: Principal, work_order_id: uuid.UUID
) -> FieldWorkOrder:
    return (await _views(db, storage, [await _mine(db, principal, work_order_id)]))[0]


# --- actions ---------------------------------------------------------------------------------


async def _begin(
    db: AsyncSession,
    storage: ObjectStorage,
    principal: Principal,
    work_order_id: uuid.UUID,
    version: int,
    action: Action,
) -> tuple[CivicIssue, WorkOrder, WorkOrderState]:
    """Lock the issue, then the work order; check version and state."""
    issue_id = (await _mine(db, principal, work_order_id)).issue_id
    issue = await db.scalar(
        select(CivicIssue)
        .where(CivicIssue.id == issue_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert issue is not None
    work_order = await _mine(db, principal, work_order_id, lock=True)
    if work_order.version != version:
        current = (await _views(db, storage, [work_order]))[0]
        raise WorkOrderConflict(details={"work_order": current.model_dump(mode="json")})
    target = next_state(WorkOrderState(work_order.state), action)
    if target is None:
        raise InvalidWorkOrderAction(details={"state": work_order.state, "action": action.value})
    return issue, work_order, target


def _apply(work_order: WorkOrder, target: WorkOrderState) -> None:
    work_order.state = target.value
    work_order.version += 1
    work_order.updated_at = datetime.now(UTC)


async def _claim_evidence(
    db: AsyncSession, principal: Principal, media_ids: list[uuid.UUID], work_order: WorkOrder
) -> list[MediaAsset]:
    """Attach the caller's completed `work_evidence` uploads to the order."""
    if not media_ids:
        return []
    found = {
        m.id: m
        for m in await db.scalars(
            select(MediaAsset)
            .where(MediaAsset.id.in_(media_ids))
            .order_by(MediaAsset.id)
            .with_for_update()
        )
    }
    invalid: list[dict[str, str]] = []
    for media_id in media_ids:
        asset = found.get(media_id)
        if asset is None or asset.owner_id != principal.user_id:
            invalid.append({"id": str(media_id), "reason": "not_found"})
        elif asset.purpose != MediaPurpose.WORK_EVIDENCE:
            invalid.append({"id": str(media_id), "reason": "wrong_purpose"})
        elif asset.status not in _USABLE:
            reason = "failed" if asset.status == MediaStatus.FAILED else "not_completed"
            invalid.append({"id": str(media_id), "reason": reason})
        elif asset.work_order_id is not None:
            invalid.append({"id": str(media_id), "reason": "already_attached"})
    if invalid:
        raise InvalidMedia(details={"media": invalid})
    for media_id in media_ids:
        found[media_id].work_order_id = work_order.id
    await db.flush()
    return [found[m] for m in media_ids]


async def accept(
    db: AsyncSession,
    storage: ObjectStorage,
    principal: Principal,
    wo_id: uuid.UUID,
    body: VersionBody,
) -> None:
    issue, work_order, target = await _begin(
        db, storage, principal, wo_id, body.version, Action.ACCEPT
    )
    _apply(work_order, target)
    add_event(
        db,
        issue,
        EventType.WORK_ORDER_ACCEPTED,
        actor_id=principal.user_id,
        visibility=Visibility.INTERNAL,
        data={"work_order_id": str(work_order.id)},
    )
    await db.flush()


async def decline(
    db: AsyncSession,
    storage: ObjectStorage,
    principal: Principal,
    wo_id: uuid.UUID,
    body: DeclineBody,
) -> None:
    issue, work_order, target = await _begin(
        db, storage, principal, wo_id, body.version, Action.DECLINE
    )
    _apply(work_order, target)
    work_order.decline_reason = body.reason
    assignment = await db.scalar(
        select(IssueAssignment)
        .where(IssueAssignment.id == work_order.assignment_id)
        .with_for_update()
    )
    assert assignment is not None
    end_assignment(assignment, AssignmentEnd.DECLINED)
    await move(
        db,
        issue,
        S.VERIFIED,
        EventType.WORK_ORDER_DECLINED,
        actor_id=principal.user_id,
        visibility=Visibility.INTERNAL,
        reason=body.reason,
        data={"work_order_id": str(work_order.id)},
    )
    await audit.record(
        db,
        action="work_order.declined",
        entity_type="work_order",
        entity_id=work_order.id,
        actor=principal,
        after={"issue_id": str(issue.id), "reason": body.reason},
    )


async def start(
    db: AsyncSession,
    storage: ObjectStorage,
    principal: Principal,
    wo_id: uuid.UUID,
    body: VersionBody,
) -> None:
    issue, work_order, target = await _begin(
        db, storage, principal, wo_id, body.version, Action.START
    )
    _apply(work_order, target)
    await move(
        db,
        issue,
        S.IN_PROGRESS,
        EventType.WORK_STARTED,
        actor_id=principal.user_id,
        visibility=Visibility.PUBLIC,
        data={"work_order_id": str(work_order.id)},
    )


async def progress(
    db: AsyncSession,
    storage: ObjectStorage,
    principal: Principal,
    wo_id: uuid.UUID,
    body: ProgressBody,
) -> None:
    issue, work_order, target = await _begin(
        db, storage, principal, wo_id, body.version, Action.PROGRESS
    )
    await _claim_evidence(db, principal, body.media_ids, work_order)
    _apply(work_order, target)
    add_event(
        db,
        issue,
        EventType.PROGRESS,
        actor_id=principal.user_id,
        visibility=Visibility.INTERNAL,
        data={
            "work_order_id": str(work_order.id),
            "note": body.note,
            "location": body.location.model_dump() if body.location else None,
            "media_ids": [str(m) for m in body.media_ids],
        },
    )
    await db.flush()


async def request_closure(
    db: AsyncSession,
    storage: ObjectStorage,
    principal: Principal,
    wo_id: uuid.UUID,
    body: ClosureRequestBody,
) -> None:
    issue, work_order, target = await _begin(
        db, storage, principal, wo_id, body.version, Action.REQUEST_CLOSURE
    )
    category = await db.scalar(select(Category).where(Category.id == issue.category_id))
    assert category is not None
    policy = closure_policy(category)
    if body.reason_code is not None and body.reason_code not in policy.reason_codes:
        raise ClosureEvidenceRequired(details={"allowed_reason_codes": policy.reason_codes})
    await _claim_evidence(db, principal, body.media_ids, work_order)
    has_after = await db.scalar(
        select(MediaAsset.id)
        .where(MediaAsset.work_order_id == work_order.id, MediaAsset.phase == MediaPhase.AFTER)
        .limit(1)
    )
    if has_after is None and body.reason_code is None:
        raise ClosureEvidenceRequired(details={"allowed_reason_codes": policy.reason_codes})
    _apply(work_order, target)
    request = ClosureRequest(
        tenant_id=issue.tenant_id,
        issue_id=issue.id,
        work_order_id=work_order.id,
        requested_by=principal.user_id,
        reason_code=body.reason_code,
        note=body.note,
    )
    db.add(request)
    await db.flush()
    await move(
        db,
        issue,
        S.PENDING_VERIFICATION,
        EventType.CLOSURE_REQUESTED,
        actor_id=principal.user_id,
        visibility=Visibility.PUBLIC,
        data={
            "closure_request_id": str(request.id),
            "reason_code": body.reason_code,
            "note": body.note,
            "media_ids": [str(m) for m in body.media_ids],
        },
    )
    await audit.record(
        db,
        action="closure.requested",
        entity_type="issue",
        entity_id=issue.id,
        actor=principal,
        after={"closure_request_id": str(request.id), "reason_code": body.reason_code},
    )
