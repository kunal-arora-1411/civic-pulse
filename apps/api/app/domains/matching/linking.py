"""Putting reports on issues (contract D.1 step 5), shared by matching,
review, merge and split.

Callers hold the matching lock for the category family and run inside one
transaction. Counts are always recounted from the reports themselves under
the issue's row lock, never incremented, so they can't drift whatever
happened before (PRD §10.2).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from geoalchemy2 import WKTElement
from sqlalchemy import distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.audit import service as audit
from app.domains.issues.models import (
    CivicIssue,
    EventType,
    IssueEvent,
    ReferenceKind,
    Visibility,
)
from app.domains.issues.references import allocate
from app.domains.media.models import MediaAsset
from app.domains.priority import service as priority
from app.domains.rbac.principal import Principal
from app.domains.reports.models import MatchingStatus, Report
from app.domains.workflow.statuses import IssueStatus

# Category families: a category and its parent chain share a root, and only
# categories in one family are compatible for matching (same category, a
# sibling, or a parent/child). Locking per family serialises exactly the
# decisions that could see each other's issues.
_FAMILY_ROOT = text(
    """
    WITH RECURSIVE chain AS (
        SELECT id, parent_id, 0 AS depth FROM categories WHERE id = :category_id
        UNION
        SELECT c.id, c.parent_id, chain.depth + 1
        FROM categories c JOIN chain ON c.id = chain.parent_id
        WHERE chain.depth < 20
    )
    SELECT id FROM chain ORDER BY depth DESC LIMIT 1
    """
)
_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")


async def family_root(db: AsyncSession, category_id: uuid.UUID) -> uuid.UUID:
    root = await db.scalar(_FAMILY_ROOT, {"category_id": category_id})
    return root or category_id


async def lock_families(
    db: AsyncSession, tenant_id: uuid.UUID, category_ids: Iterable[uuid.UUID]
) -> None:
    """Take the matching lock (tenant, category family) for each category,
    in a fixed order so two callers can't deadlock. Held until commit."""
    roots = {await family_root(db, category_id) for category_id in set(category_ids)}
    for root in sorted(roots, key=str):
        await db.execute(_LOCK, {"key": f"matching:{tenant_id}:{root}"})


async def lock_issues(
    db: AsyncSession, issue_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, CivicIssue]:
    """Row-lock issues in id order (after the family locks) and return them fresh."""
    rows = await db.scalars(
        select(CivicIssue)
        .where(CivicIssue.id.in_(sorted(set(issue_ids))))
        .order_by(CivicIssue.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return {issue.id: issue for issue in rows}


async def refresh_counts(db: AsyncSession, issue: CivicIssue) -> None:
    """Recount from the linked reports. The caller holds the issue's lock."""
    await db.flush()
    total, unique = (
        await db.execute(
            select(func.count(), func.count(distinct(Report.reporter_id))).where(
                Report.issue_id == issue.id
            )
        )
    ).one()
    issue.report_count = int(total)
    issue.unique_reporter_count = int(unique)


async def first_media_id(db: AsyncSession, report_ids: Iterable[uuid.UUID]) -> uuid.UUID | None:
    ids = list(report_ids)
    if not ids:
        return None
    return await db.scalar(
        select(MediaAsset.id)
        .join(Report, Report.id == MediaAsset.report_id)
        .where(MediaAsset.report_id.in_(ids))
        .order_by(Report.created_at, Report.id, MediaAsset.position)
        .limit(1)
    )


async def link_report(
    db: AsyncSession,
    report: Report,
    issue: CivicIssue,
    *,
    actor: Principal | None,
    reason: str,
) -> None:
    """Put a report on an existing (locked, not merged) issue."""
    assert issue.merged_into_id is None
    report.issue_id = issue.id
    report.matching_status = MatchingStatus.LINKED
    await refresh_counts(db, issue)
    if issue.cover_media_id is None:
        issue.cover_media_id = await first_media_id(db, [report.id])
    issue.version += 1
    db.add(
        IssueEvent(
            tenant_id=issue.tenant_id,
            issue_id=issue.id,
            report_id=report.id,
            type=EventType.REPORT_LINKED,
            # Staff timeline only: citizens follow the issue's status, and a
            # neighbour's report joining it isn't theirs to see.
            visibility=Visibility.INTERNAL,
            actor_id=actor.user_id if actor else None,
            data={"reason": reason},
        )
    )
    await db.flush()
    await audit.record(
        db,
        action="issue.report_linked",
        entity_type="issue",
        entity_id=issue.id,
        actor=actor,
        after={
            "report_id": str(report.id),
            "reason": reason,
            "report_count": issue.report_count,
            "unique_reporter_count": issue.unique_reporter_count,
        },
    )
    await priority.recompute(db, issue.id)


async def create_issue_for_report(
    db: AsyncSession, report: Report, *, actor: Principal | None, reason: str
) -> CivicIssue:
    """Start a new issue from a report, at the report's location."""
    location = (
        await db.execute(
            select(func.ST_X(Report.location), func.ST_Y(Report.location)).where(
                Report.id == report.id
            )
        )
    ).one()
    issue = CivicIssue(
        id=uuid.uuid4(),
        tenant_id=report.tenant_id,
        reference=await allocate(db, report.tenant_id, ReferenceKind.ISSUE),
        category_id=report.category_id,
        status=IssueStatus.REPORTED,
        location=WKTElement(f"POINT({location[0]} {location[1]})", srid=4326),
        address_text=report.address_text,
        ward_id=report.ward_id,
        report_count=0,
        unique_reporter_count=0,
        cover_media_id=await first_media_id(db, [report.id]),
    )
    db.add(issue)
    await db.flush()
    report.issue_id = issue.id
    report.matching_status = MatchingStatus.NEW_ISSUE
    await refresh_counts(db, issue)
    db.add(
        IssueEvent(
            tenant_id=issue.tenant_id,
            issue_id=issue.id,
            report_id=report.id,
            type=EventType.CREATED,
            to_status=IssueStatus.REPORTED,
            visibility=Visibility.PUBLIC,
            # The citizen created it, unless a reviewer decided it is new.
            actor_id=actor.user_id if actor else report.reporter_id,
            data={"reason": reason},
        )
    )
    await db.flush()
    await audit.record(
        db,
        action="issue.created",
        entity_type="issue",
        entity_id=issue.id,
        actor=actor,
        after={
            "reference": issue.reference,
            "status": issue.status,
            "report_id": str(report.id),
            "reason": reason,
        },
    )
    await priority.recompute(db, issue.id)
    return issue
