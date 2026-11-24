"""Merging and splitting issues (FR-033, FR-034) and related-issue links
(FR-060).

Merges and splits move reports between issues, so they take the same
locks as matching, in the same order: the advisory lock for every category
family involved, then the issue rows by id. Nothing is ever deleted: a
merged issue keeps its reference and history and points at the survivor,
reports keep their identifiers, and both sides get timeline and audit
entries. Counts are recounted from the reports afterwards.
"""

from __future__ import annotations

import uuid
from typing import Any

from geoalchemy2 import WKTElement
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.domains.audit import service as audit
from app.domains.issues.errors import (
    CannotEmptyIssue,
    InvalidMerge,
    IssueMerged,
    ReasonRequired,
    VersionConflict,
)
from app.domains.issues.models import (
    CivicIssue,
    EventType,
    IssueEvent,
    IssueRelation,
    ReferenceKind,
    Visibility,
)
from app.domains.issues.references import allocate
from app.domains.issues.schemas import (
    ExistingIssueTarget,
    MergeRequest,
    RelatedRequest,
    SplitRequest,
)
from app.domains.issues.service import get_in_scope
from app.domains.matching import linking
from app.domains.media.models import MediaAsset
from app.domains.priority import service as priority
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.reports.models import Report
from app.domains.workflow.statuses import IssueStatus


def _require_reason(reason: str | None, action: str) -> str:
    if not reason:
        raise ReasonRequired(details={"action": action})
    return reason


def _event(
    issue: CivicIssue,
    type_: EventType,
    *,
    actor: Principal,
    other: uuid.UUID | None,
    reason: str | None,
    visibility: Visibility,
    data: dict[str, Any] | None = None,
) -> IssueEvent:
    return IssueEvent(
        tenant_id=issue.tenant_id,
        issue_id=issue.id,
        type=type_,
        related_issue_id=other,
        reason=reason,
        visibility=visibility,
        actor_id=actor.user_id,
        data=data,
    )


async def _report_ids(db: AsyncSession, issue_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        await db.scalars(
            select(Report.id)
            .where(Report.issue_id == issue_id)
            .order_by(Report.created_at, Report.id)
        )
    )


# --- merge ---------------------------------------------------------------------------------


async def merge(
    db: AsyncSession, principal: Principal, survivor_id: uuid.UUID, body: MergeRequest
) -> None:
    """Merge the source issues into `survivor_id`, which keeps its status."""
    if survivor_id in body.source_issue_ids:
        raise InvalidMerge(
            "An issue can't be merged into itself.", details={"reason": "merge_into_itself"}
        )
    perm = Permission.ISSUE_MERGE
    survivor = await get_in_scope(db, principal, survivor_id, permission=perm)
    sources = [
        await get_in_scope(db, principal, source_id, permission=perm)
        for source_id in body.source_issue_ids
    ]
    reason = _require_reason(body.reason, "merge")

    await linking.lock_families(
        db, survivor.tenant_id, [survivor.category_id, *(s.category_id for s in sources)]
    )
    locked = await linking.lock_issues(db, [survivor_id, *body.source_issue_ids])
    survivor = locked[survivor_id]
    if survivor.merged_into_id is not None:
        raise InvalidMerge(
            "This issue was itself merged into another.",
            details={"reason": "target_is_merged", "merged_into": str(survivor.merged_into_id)},
        )
    if survivor.version != body.version:
        raise VersionConflict(details={"version": survivor.version})
    already = [str(i) for i in body.source_issue_ids if locked[i].merged_into_id is not None]
    if already:
        raise InvalidMerge(
            "Some of these issues were already merged.",
            details={"reason": "source_is_merged", "issue_ids": already},
        )

    before = {
        "report_count": survivor.report_count,
        "unique_reporter_count": survivor.unique_reporter_count,
        "version": survivor.version,
    }
    moved: dict[str, list[str]] = {}
    for source_id in body.source_issue_ids:
        source = locked[source_id]
        report_ids = await _report_ids(db, source_id)
        moved[str(source_id)] = [str(r) for r in report_ids]
        await db.execute(
            update(Report)
            .where(Report.issue_id == source_id)
            .values(issue_id=survivor_id)
            .execution_options(synchronize_session=False)
        )
        # Issues merged into the source earlier now point at the survivor,
        # so a redirect never takes more than one hop.
        await db.execute(
            update(CivicIssue)
            .where(CivicIssue.merged_into_id == source_id)
            .values(merged_into_id=survivor_id)
            .execution_options(synchronize_session=False)
        )
        source.merged_into_id = survivor_id
        source.version += 1
        await linking.refresh_counts(db, source)
        db.add(
            _event(
                source,
                EventType.MERGED_INTO,
                actor=principal,
                other=survivor_id,
                reason=reason,
                # No report is left on the source for a citizen to follow.
                visibility=Visibility.INTERNAL,
                data={"report_ids": moved[str(source_id)]},
            )
        )
        db.add(
            _event(
                survivor,
                EventType.MERGED,
                actor=principal,
                other=source_id,
                reason=reason,
                visibility=Visibility.PUBLIC,
                data={"report_ids": moved[str(source_id)]},
            )
        )
        await db.flush()
        await audit.record(
            db,
            action="issue.merged_into",
            entity_type="issue",
            entity_id=source_id,
            actor=principal,
            before={"merged_into_id": None, "report_ids": moved[str(source_id)]},
            after={"merged_into_id": str(survivor_id), "reason": reason},
        )

    await linking.refresh_counts(db, survivor)
    if survivor.cover_media_id is None:
        survivor.cover_media_id = await linking.first_media_id(
            db, await _report_ids(db, survivor_id)
        )
    survivor.version += 1
    await db.flush()
    await audit.record(
        db,
        action="issue.merged",
        entity_type="issue",
        entity_id=survivor_id,
        actor=principal,
        before=before,
        after={
            "source_issue_ids": [str(i) for i in body.source_issue_ids],
            "moved_report_ids": moved,
            "report_count": survivor.report_count,
            "unique_reporter_count": survivor.unique_reporter_count,
            "version": survivor.version,
            "reason": reason,
        },
    )
    for issue_id in (survivor_id, *body.source_issue_ids):
        await priority.recompute(db, issue_id)


# --- split ---------------------------------------------------------------------------------


async def split(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID, body: SplitRequest
) -> uuid.UUID:
    """Move some reports to a new or existing issue. Returns the target's id."""
    perm = Permission.ISSUE_MERGE
    source = await get_in_scope(db, principal, issue_id, permission=perm)
    target: CivicIssue | None = None
    if isinstance(body.target, ExistingIssueTarget):
        if body.target.issue_id == issue_id:
            raise ValidationFailed(
                "Reports can't be moved to the issue they are on.",
                details={
                    "errors": [
                        {
                            "loc": ["body", "target", "issue_id"],
                            "msg": "The target is the source issue.",
                            "type": "value_error",
                        }
                    ]
                },
            )
        target = await get_in_scope(db, principal, body.target.issue_id, permission=perm)
    reason = _require_reason(body.reason, "split")

    families = [source.category_id] + ([target.category_id] if target else [])
    await linking.lock_families(db, source.tenant_id, families)
    locked = await linking.lock_issues(db, [issue_id] + ([target.id] if target else []))
    source = locked[issue_id]
    if source.merged_into_id is not None:
        raise IssueMerged(details={"merged_into": str(source.merged_into_id)})
    if source.version != body.version:
        raise VersionConflict(details={"version": source.version})
    if target is not None:
        target = locked[target.id]
        if target.merged_into_id is not None:
            raise IssueMerged(
                "The target issue was merged into another.",
                details={"merged_into": str(target.merged_into_id)},
            )

    reports = list(
        await db.scalars(
            select(Report)
            .where(Report.id.in_(body.report_ids))
            .order_by(Report.created_at, Report.id)
            .with_for_update()
        )
    )
    foreign = sorted(
        {str(r) for r in body.report_ids} - {str(r.id) for r in reports if r.issue_id == issue_id}
    )
    if foreign:
        raise ValidationFailed(
            "Some reports aren't on this issue.",
            details={
                "errors": [
                    {
                        "loc": ["body", "report_ids"],
                        "msg": f"Not on this issue: {', '.join(foreign)}.",
                        "type": "value_error",
                    }
                ],
                "report_ids": foreign,
            },
        )
    total = await db.scalar(select(func.count()).where(Report.issue_id == issue_id))
    if len(reports) >= int(total or 0):
        raise CannotEmptyIssue(details={"report_count": int(total or 0)})

    created = target is None
    if target is None:
        first = reports[0]  # the oldest moved report
        lng, lat = (
            await db.execute(
                select(func.ST_X(Report.location), func.ST_Y(Report.location)).where(
                    Report.id == first.id
                )
            )
        ).one()
        target = CivicIssue(
            id=uuid.uuid4(),
            tenant_id=source.tenant_id,
            reference=await allocate(db, source.tenant_id, ReferenceKind.ISSUE),
            category_id=source.category_id,
            status=IssueStatus.REPORTED,
            location=WKTElement(f"POINT({lng} {lat})", srid=4326),
            address_text=first.address_text,
            ward_id=first.ward_id,
            report_count=0,
            unique_reporter_count=0,
        )
        db.add(target)
        await db.flush()
        db.add(
            IssueEvent(
                tenant_id=target.tenant_id,
                issue_id=target.id,
                report_id=first.id,
                type=EventType.CREATED,
                to_status=IssueStatus.REPORTED,
                visibility=Visibility.PUBLIC,
                actor_id=principal.user_id,
                related_issue_id=issue_id,
                data={"reason": "split"},
            )
        )

    moved_ids = [r.id for r in reports]
    for report in reports:
        report.issue_id = target.id
    await linking.refresh_counts(db, source)
    await linking.refresh_counts(db, target)
    remaining = await _report_ids(db, issue_id)
    if source.cover_media_id is not None and not await _cover_on(
        db, source.cover_media_id, remaining
    ):
        source.cover_media_id = await linking.first_media_id(db, remaining)
    if target.cover_media_id is None:
        target.cover_media_id = await linking.first_media_id(db, moved_ids)
    source.version += 1
    if not created:
        target.version += 1
    moved = [str(r) for r in moved_ids]
    db.add(
        _event(
            source,
            EventType.SPLIT,
            actor=principal,
            other=target.id,
            reason=reason,
            visibility=Visibility.INTERNAL,
            data={"report_ids": moved, "direction": "out"},
        )
    )
    db.add(
        _event(
            target,
            EventType.SPLIT,
            actor=principal,
            other=issue_id,
            reason=reason,
            visibility=Visibility.INTERNAL,
            data={"report_ids": moved, "direction": "in"},
        )
    )
    await db.flush()
    await audit.record(
        db,
        action="issue.split",
        entity_type="issue",
        entity_id=issue_id,
        actor=principal,
        after={
            "report_ids": moved,
            "target_issue_id": str(target.id),
            "target_created": created,
            "source_report_count": source.report_count,
            "target_report_count": target.report_count,
            "reason": reason,
        },
    )
    await priority.recompute(db, issue_id)
    await priority.recompute(db, target.id)
    return target.id


async def _cover_on(db: AsyncSession, media_id: uuid.UUID, report_ids: list[uuid.UUID]) -> bool:
    owner = await db.scalar(select(MediaAsset.report_id).where(MediaAsset.id == media_id))
    return owner in report_ids


# --- related issues --------------------------------------------------------------------------


def _pair(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    return (a, b) if a < b else (b, a)


async def add_related(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID, body: RelatedRequest
) -> None:
    perm = Permission.ISSUE_UPDATE
    issue = await get_in_scope(db, principal, issue_id, permission=perm)
    if body.issue_id == issue_id:
        raise ValidationFailed(
            "An issue can't be related to itself.",
            details={
                "errors": [
                    {"loc": ["body", "issue_id"], "msg": "Same issue.", "type": "value_error"}
                ]
            },
        )
    other = await get_in_scope(db, principal, body.issue_id, permission=perm)
    for item in (issue, other):
        if item.merged_into_id is not None:
            raise IssueMerged(details={"issue_id": str(item.id)})
    low, high = _pair(issue_id, body.issue_id)
    inserted = await db.scalar(
        pg_insert(IssueRelation)
        .values(
            tenant_id=issue.tenant_id,
            issue_id=low,
            related_issue_id=high,
            note=body.note,
            created_by=principal.user_id,
        )
        .on_conflict_do_nothing(constraint="pk_issue_relations")
        .returning(IssueRelation.issue_id)
    )
    if inserted is None:
        raise Conflict("These issues are already marked as related.")
    await audit.record(
        db,
        action="issue.related_added",
        entity_type="issue",
        entity_id=issue_id,
        actor=principal,
        after={"related_issue_id": str(body.issue_id), "note": body.note},
    )


async def remove_related(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID, other_id: uuid.UUID
) -> None:
    await get_in_scope(db, principal, issue_id, permission=Permission.ISSUE_UPDATE)
    low, high = _pair(issue_id, other_id)
    removed = (
        await db.execute(
            delete(IssueRelation)
            .where(IssueRelation.issue_id == low, IssueRelation.related_issue_id == high)
            .returning(IssueRelation.note)
        )
    ).first()
    if removed is None:
        raise NotFound()
    await audit.record(
        db,
        action="issue.related_removed",
        entity_type="issue",
        entity_id=issue_id,
        actor=principal,
        before={"related_issue_id": str(other_id), "note": removed[0]},
    )
