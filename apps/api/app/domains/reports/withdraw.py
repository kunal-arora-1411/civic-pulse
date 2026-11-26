"""A citizen withdrawing their own report (FR-018)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.domains.audit import service as audit
from app.domains.issues.errors import InvalidTransition
from app.domains.issues.models import EventType, IssueEvent, Visibility
from app.domains.matching import linking
from app.domains.priority import service as priority
from app.domains.rbac.principal import Principal
from app.domains.reports.models import Report, ReportStatus
from app.domains.workflow.statuses import IssueStatus

_FINAL = (IssueStatus.RESOLVED, IssueStatus.CLOSED)


async def withdraw(db: AsyncSession, principal: Principal, report_id: uuid.UUID) -> None:
    """Mark the report withdrawn. It stays linked to its issue as a
    tombstone, so history and audit keep it, but stops counting. Doing it
    twice is a no-op."""
    found = await db.scalar(
        select(Report).where(Report.id == report_id, Report.reporter_id == principal.user_id)
    )
    if found is None:
        raise NotFound()
    if found.status == ReportStatus.WITHDRAWN:
        return
    if found.issue_id is None:
        # Matching or review would still place it; let that finish first.
        raise InvalidTransition(details={"reason": "matching_pending"})
    # Issue first, then the report: the order matching locks them in.
    issue = (await linking.lock_issues(db, [found.issue_id]))[found.issue_id]
    report = await db.scalar(
        select(Report)
        .where(Report.id == report_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert report is not None
    if report.status == ReportStatus.WITHDRAWN:
        return
    if issue.status in _FINAL:
        raise InvalidTransition(details={"reason": "issue_" + issue.status})
    report.status = ReportStatus.WITHDRAWN
    await linking.refresh_counts(db, issue)
    issue.version += 1
    db.add(
        IssueEvent(
            tenant_id=issue.tenant_id,
            issue_id=issue.id,
            report_id=report.id,
            type=EventType.REPORT_WITHDRAWN,
            visibility=Visibility.INTERNAL,
            actor_id=principal.user_id,
            data={"report_id": str(report.id)},
        )
    )
    await db.flush()
    await priority.recompute(db, issue.id)
    await audit.record(
        db,
        action="report.withdrawn",
        entity_type="report",
        entity_id=report.id,
        actor=principal,
        after={"issue_id": str(issue.id), "report_count": issue.report_count},
    )
