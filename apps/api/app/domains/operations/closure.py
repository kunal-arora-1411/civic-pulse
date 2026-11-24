"""Closure approval, citizen verification, reopening and the resolution
window (FR-058, FR-070 to FR-074)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session_factory
from app.core.errors import NotFound
from app.core.logging import log_fields
from app.core.tenancy import set_tenant, system_session
from app.domains.audit import service as audit
from app.domains.categories.models import Category
from app.domains.categories.service import closure_policy
from app.domains.config import service as config
from app.domains.issues.errors import InvalidTransition
from app.domains.issues.models import CivicIssue, EventType, Visibility
from app.domains.issues.service import get_in_scope
from app.domains.operations.errors import AlreadyVerified, NotEligible
from app.domains.operations.models import (
    ClosureRequest,
    ClosureState,
    IssueVerification,
    VerificationOutcome,
    WorkOrder,
)
from app.domains.operations.schemas import (
    ApproveClosure,
    RejectClosure,
    ReopenRequest,
    VerificationCreate,
)
from app.domains.operations.service import (
    add_event,
    advance,
    check_version,
    issue_for_citizen,
    move,
)
from app.domains.operations.states import Action, Decision, decide
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.reports.models import Report, ReportStatus
from app.domains.reports.service import enforce_staff_mfa
from app.domains.workflow.statuses import IssueStatus as S

logger = logging.getLogger(__name__)


async def _pending_request(db: AsyncSession, issue: CivicIssue) -> ClosureRequest:
    request = await db.scalar(
        select(ClosureRequest)
        .where(ClosureRequest.issue_id == issue.id, ClosureRequest.state == ClosureState.PENDING)
        .with_for_update()
    )
    if request is None or issue.status != S.PENDING_VERIFICATION:
        raise InvalidTransition(details={"from_status": issue.status, "reason": "no_closure"})
    return request


async def _work_order(db: AsyncSession, request: ClosureRequest) -> WorkOrder | None:
    if request.work_order_id is None:
        return None
    return await db.scalar(
        select(WorkOrder)
        .where(WorkOrder.id == request.work_order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _decide(
    request: ClosureRequest, state: ClosureState, actor_id: uuid.UUID | None, reason: str | None
) -> None:
    request.state = state.value
    request.decided_by = actor_id
    request.decided_at = datetime.now(UTC)
    request.decision_reason = reason


async def _resolve(
    db: AsyncSession,
    issue: CivicIssue,
    request: ClosureRequest,
    *,
    actor_id: uuid.UUID | None,
    public_note: str | None,
    by: str,
) -> None:
    _decide(request, ClosureState.APPROVED, actor_id, None)
    work_order = await _work_order(db, request)
    if work_order is not None:
        advance(work_order, Action.APPROVE)
    await move(
        db,
        issue,
        S.RESOLVED,
        EventType.CLOSURE_APPROVED,
        actor_id=actor_id,
        visibility=Visibility.PUBLIC,
        public_note=public_note,
        data={"closure_request_id": str(request.id), "by": by},
    )


async def _send_back(
    db: AsyncSession,
    issue: CivicIssue,
    request: ClosureRequest,
    *,
    actor_id: uuid.UUID | None,
    reason: str | None,
    by: str,
) -> None:
    _decide(request, ClosureState.REJECTED, actor_id, reason)
    work_order = await _work_order(db, request)
    if work_order is not None:
        advance(work_order, Action.REJECT)
    await move(
        db,
        issue,
        S.IN_PROGRESS,
        EventType.CLOSURE_REJECTED,
        actor_id=actor_id,
        visibility=Visibility.INTERNAL,
        reason=reason,
        data={"closure_request_id": str(request.id), "by": by},
    )


# --- supervisor (FR-071) ---------------------------------------------------------------------


async def approve(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID, body: ApproveClosure
) -> None:
    issue = await get_in_scope(
        db, principal, issue_id, for_update=True, permission=Permission.ISSUE_APPROVE_CLOSURE
    )
    check_version(issue, body.version)
    request = await _pending_request(db, issue)
    await _resolve(
        db,
        issue,
        request,
        actor_id=principal.user_id,
        public_note=body.public_note,
        by="supervisor",
    )
    await audit.record(
        db,
        action="closure.approved",
        entity_type="issue",
        entity_id=issue.id,
        actor=principal,
        after={"closure_request_id": str(request.id), "version": issue.version},
    )


async def reject(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID, body: RejectClosure
) -> None:
    issue = await get_in_scope(
        db, principal, issue_id, for_update=True, permission=Permission.ISSUE_APPROVE_CLOSURE
    )
    check_version(issue, body.version)
    request = await _pending_request(db, issue)
    await _send_back(
        db, issue, request, actor_id=principal.user_id, reason=body.reason, by="supervisor"
    )
    await audit.record(
        db,
        action="closure.rejected",
        entity_type="issue",
        entity_id=issue.id,
        actor=principal,
        after={"closure_request_id": str(request.id), "reason": body.reason},
    )


# --- citizens (FR-072 to FR-074) -------------------------------------------------------------


async def citizen_report_id(db: AsyncSession, principal: Principal, issue: CivicIssue) -> uuid.UUID:
    """The caller's oldest live report on the issue: what makes them eligible."""
    report_id = await db.scalar(
        select(Report.id)
        .where(
            Report.issue_id == issue.id,
            Report.reporter_id == principal.user_id,
            Report.status == ReportStatus.ACCEPTED,
        )
        .order_by(Report.created_at, Report.id)
        .limit(1)
    )
    if report_id is None:
        raise NotEligible()
    return report_id


async def verify(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID, body: VerificationCreate
) -> uuid.UUID:
    """Record a citizen's answer and apply the verification rule. Returns
    the caller's report id (the response is its owner view)."""
    issue = await issue_for_citizen(db, issue_id)
    report_id = await citizen_report_id(db, principal, issue)
    if issue.status not in (S.PENDING_VERIFICATION, S.RESOLVED):
        raise InvalidTransition(details={"from_status": issue.status, "reason": "not_verifiable"})
    # The round being answered: the pending request, or the approved one
    # that resolved the issue.
    request = await db.scalar(
        select(ClosureRequest)
        .where(
            ClosureRequest.issue_id == issue.id,
            ClosureRequest.state
            == (
                ClosureState.PENDING
                if issue.status == S.PENDING_VERIFICATION
                else ClosureState.APPROVED
            ),
        )
        .order_by(ClosureRequest.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if request is None:
        raise InvalidTransition(details={"from_status": issue.status, "reason": "no_closure"})
    try:
        async with db.begin_nested():
            db.add(
                IssueVerification(
                    tenant_id=issue.tenant_id,
                    issue_id=issue.id,
                    closure_request_id=request.id,
                    user_id=principal.user_id,
                    outcome=body.outcome.value,
                    note=body.note,
                )
            )
    except IntegrityError as exc:
        raise AlreadyVerified() from exc

    data = {"closure_request_id": str(request.id), "outcome": body.outcome.value, "note": body.note}
    if issue.status == S.RESOLVED:
        if body.outcome == VerificationOutcome.UNRESOLVED:
            await move(
                db,
                issue,
                S.REOPENED,
                EventType.REOPENED,
                actor_id=principal.user_id,
                visibility=Visibility.PUBLIC,
                reason=body.note,
                data={"by": "citizen", **data},
            )
            await audit.record(
                db,
                action="issue.reopened",
                entity_type="issue",
                entity_id=issue.id,
                actor=principal,
                after=data,
            )
        else:
            add_event(
                db,
                issue,
                EventType.VERIFICATION,
                actor_id=principal.user_id,
                visibility=Visibility.INTERNAL,
                data=data,
            )
        return report_id

    category = await db.scalar(select(Category).where(Category.id == issue.category_id))
    assert category is not None
    outcomes = [
        VerificationOutcome(o)
        for o in await db.scalars(
            select(IssueVerification.outcome).where(
                IssueVerification.closure_request_id == request.id
            )
        )
    ]
    decision = decide(
        outcomes,
        requires_approval=closure_policy(category).requires_approval,
        confirmations_required=(await config.closure_config(db)).confirmations_required,
    )
    add_event(
        db,
        issue,
        EventType.VERIFICATION,
        actor_id=principal.user_id,
        visibility=Visibility.INTERNAL,
        data=data,
    )
    if decision == Decision.RESOLVE:
        await _resolve(db, issue, request, actor_id=None, public_note=None, by="citizens")
    elif decision == Decision.SEND_BACK:
        await _send_back(
            db, issue, request, actor_id=principal.user_id, reason=body.note, by="citizen"
        )
    await db.flush()
    return report_id


async def reopen(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID, body: ReopenRequest
) -> bool:
    """Reopen a resolved or closed issue (FR-058). Staff with `issue:update`
    in scope, or an eligible citizen. Returns True when the caller acted as
    staff (the response is then the issue detail)."""
    staff = principal.has(Permission.ISSUE_UPDATE)
    if staff:
        enforce_staff_mfa(principal)
        issue = await get_in_scope(
            db, principal, issue_id, for_update=True, permission=Permission.ISSUE_UPDATE
        )
    elif principal.has(Permission.ISSUE_VERIFY):
        issue = await issue_for_citizen(db, issue_id)
        await citizen_report_id(db, principal, issue)
    else:
        raise NotFound()
    if issue.status not in (S.RESOLVED, S.CLOSED):
        raise InvalidTransition(
            details={"from_status": issue.status, "to_status": S.REOPENED.value}
        )
    await move(
        db,
        issue,
        S.REOPENED,
        EventType.REOPENED,
        actor_id=principal.user_id,
        visibility=Visibility.PUBLIC,
        reason=body.reason,
        data={"by": "staff" if staff else "citizen"},
    )
    await audit.record(
        db,
        action="issue.reopened",
        entity_type="issue",
        entity_id=issue.id,
        actor=principal,
        after={"reason": body.reason, "by": "staff" if staff else "citizen"},
    )
    return staff


# --- resolution window (FR-058) --------------------------------------------------------------


async def close_expired(now: datetime | None = None) -> int:
    """Close every `resolved` issue whose resolution window has passed, in
    every tenant. Idempotent: Beat runs it every 15 minutes."""
    now = now or datetime.now(UTC)
    async with system_session(reason="resolution window: find tenants") as db:
        tenant_ids = list(
            await db.scalars(
                select(CivicIssue.tenant_id).where(CivicIssue.status == S.RESOLVED).distinct()
            )
        )
    closed = 0
    for tenant_id in tenant_ids:
        try:
            closed += await _close_tenant(tenant_id, now)
        except Exception as exc:  # one tenant's failure mustn't stop the others
            logger.exception(
                "resolution window failed",
                extra=log_fields(tenant_id=str(tenant_id), error=repr(exc)),
            )
    return closed


async def _close_tenant(tenant_id: uuid.UUID, now: datetime) -> int:
    # Tenant-scoped, not the bypass: config and workflow reads must only
    # see this tenant's rows.
    async with get_session_factory()() as db:
        await set_tenant(db, tenant_id)
        window = timedelta(hours=(await config.closure_config(db)).resolution_window_hours)
        issues = list(
            await db.scalars(
                select(CivicIssue)
                .where(
                    CivicIssue.tenant_id == tenant_id,
                    CivicIssue.status == S.RESOLVED,
                    CivicIssue.resolved_at <= now - window,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for issue in issues:
            await move(
                db, issue, S.CLOSED, EventType.CLOSED, actor_id=None, visibility=Visibility.PUBLIC
            )
            await audit.record(
                db,
                action="issue.closed",
                entity_type="issue",
                entity_id=issue.id,
                tenant_id=tenant_id,
                after={"resolved_at": issue.resolved_at.isoformat() if issue.resolved_at else None},
            )
        await db.commit()
        return len(issues)
