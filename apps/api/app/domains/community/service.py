"""Community support: "I face this too" (+1) and following an issue.

A citizen supports an issue at most once; supporting also follows it.
The issue keeps a `support_count`, and the priority rules turn support
from citizens who did not report it into a small, capped bonus
(app/domains/priority/rules.py), so support can raise an issue in the
queue but never decides its priority alone.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.domains.community.models import IssueSupport
from app.domains.community.schemas import SupportState
from app.domains.issues.errors import InvalidTransition, IssueMerged
from app.domains.issues.models import CivicIssue
from app.domains.priority import service as priority
from app.domains.rbac.principal import Principal
from app.domains.workflow.statuses import IssueStatus

# Nothing left to support: the issue was turned down or is finished.
UNSUPPORTABLE = frozenset({IssueStatus.REJECTED, IssueStatus.CLOSED})


async def _issue(db: AsyncSession, issue_id: uuid.UUID, *, for_update: bool) -> CivicIssue:
    stmt = select(CivicIssue).where(CivicIssue.id == issue_id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    issue = await db.scalar(stmt)
    if issue is None:
        raise NotFound()
    return issue


async def _state(db: AsyncSession, principal: Principal, issue: CivicIssue) -> SupportState:
    supported = await db.scalar(
        select(func.count())
        .select_from(IssueSupport)
        .where(IssueSupport.issue_id == issue.id, IssueSupport.user_id == principal.user_id)
    )
    return SupportState(
        issue_id=issue.id, support_count=issue.support_count, supported=bool(supported)
    )


async def _recount(db: AsyncSession, issue: CivicIssue) -> None:
    issue.support_count = int(
        await db.scalar(
            select(func.count()).select_from(IssueSupport).where(IssueSupport.issue_id == issue.id)
        )
        or 0
    )
    await priority.recompute(db, issue.id)


async def get_state(db: AsyncSession, principal: Principal, issue_id: uuid.UUID) -> SupportState:
    return await _state(db, principal, await _issue(db, issue_id, for_update=False))


async def support(db: AsyncSession, principal: Principal, issue_id: uuid.UUID) -> SupportState:
    """Add the caller's support. Supporting twice is harmless."""
    issue = await _issue(db, issue_id, for_update=True)
    if issue.merged_into_id is not None:
        raise IssueMerged(details={"merged_into_id": str(issue.merged_into_id)})
    if issue.status in UNSUPPORTABLE:
        raise InvalidTransition(details={"from_status": issue.status, "reason": "not_supportable"})
    await db.execute(
        insert(IssueSupport)
        .values(tenant_id=issue.tenant_id, issue_id=issue.id, user_id=principal.user_id)
        .on_conflict_do_nothing(index_elements=["issue_id", "user_id"])
    )
    await _recount(db, issue)
    return await _state(db, principal, issue)


async def withdraw(db: AsyncSession, principal: Principal, issue_id: uuid.UUID) -> SupportState:
    """Remove the caller's support (and stop following). Idempotent."""
    issue = await _issue(db, issue_id, for_update=True)
    await db.execute(
        delete(IssueSupport).where(
            IssueSupport.issue_id == issue.id, IssueSupport.user_id == principal.user_id
        )
    )
    await _recount(db, issue)
    return await _state(db, principal, issue)
