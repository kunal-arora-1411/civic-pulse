"""Manual changes to what the rules decided: severity and priority
overrides (FR-038, FR-043) and the operator's category correction (FR-021).

Each is a deliberate edit: the issue row is locked, the version checked
and bumped, the change audited with before and after and written to the
staff timeline (internal; citizens don't see these).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailed
from app.domains.audit import service as audit
from app.domains.categories.models import Category
from app.domains.issues.errors import IssueMerged, ReasonRequired, VersionConflict
from app.domains.issues.models import CivicIssue, EventType, IssueEvent, SeveritySource, Visibility
from app.domains.issues.schemas import CategoryChange, PriorityOverride, SeverityOverride
from app.domains.issues.service import get_in_scope
from app.domains.matching import linking
from app.domains.priority import service as priority
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.reports.models import CategorySource, Report


async def _locked(
    db: AsyncSession,
    principal: Principal,
    issue_id: uuid.UUID,
    version: int,
    permission: Permission,
) -> CivicIssue:
    issue = await get_in_scope(db, principal, issue_id, for_update=True, permission=permission)
    if issue.merged_into_id is not None:
        raise IssueMerged(details={"merged_into": str(issue.merged_into_id)})
    if issue.version != version:
        raise VersionConflict(details={"version": issue.version})
    return issue


def _timeline(
    issue: CivicIssue,
    type_: EventType,
    principal: Principal,
    reason: str | None,
    data: dict[str, Any],
) -> IssueEvent:
    return IssueEvent(
        tenant_id=issue.tenant_id,
        issue_id=issue.id,
        type=type_,
        reason=reason,
        visibility=Visibility.INTERNAL,
        actor_id=principal.user_id,
        data=data,
    )


async def set_severity(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID, body: SeverityOverride
) -> None:
    issue = await _locked(db, principal, issue_id, body.version, Permission.ISSUE_UPDATE)
    if body.severity is not None and not body.reason:
        raise ReasonRequired(details={"field": "severity"})
    before = {
        "level": issue.severity,
        "source": issue.severity_source,
        "reason": issue.severity_reason,
    }
    if body.severity is not None:
        issue.severity = body.severity.value
        issue.severity_source = SeveritySource.OVERRIDE
        issue.severity_reason = body.reason
    else:
        issue.severity_source = SeveritySource.RULE
        issue.severity_reason = None  # the rules fill it in again
    issue.version += 1
    await db.flush()
    await priority.recompute(db, issue.id)
    after = {
        "level": issue.severity,
        "source": issue.severity_source,
        "reason": issue.severity_reason,
    }
    db.add(
        _timeline(
            issue, EventType.SEVERITY_CHANGED, principal, body.reason, {"from": before, "to": after}
        )
    )
    await db.flush()
    await audit.record(
        db,
        action="issue.severity_overridden" if body.severity else "issue.severity_override_cleared",
        entity_type="issue",
        entity_id=issue.id,
        actor=principal,
        before=before,
        after={**after, "version": issue.version},
    )


async def set_priority(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID, body: PriorityOverride
) -> None:
    issue = await _locked(db, principal, issue_id, body.version, Permission.ISSUE_SET_PRIORITY)
    if body.band is not None and not body.reason:
        raise ReasonRequired(details={"field": "band"})
    before = {"band": issue.priority_override_band, "reason": issue.priority_override_reason}
    issue.priority_override_band = body.band.value if body.band else None
    issue.priority_override_reason = body.reason if body.band else None
    issue.version += 1
    after = {"band": issue.priority_override_band, "reason": issue.priority_override_reason}
    db.add(
        _timeline(
            issue,
            EventType.PRIORITY_CHANGED,
            principal,
            body.reason,
            {"from": before, "to": after, "computed_band": issue.priority_band},
        )
    )
    await db.flush()
    await audit.record(
        db,
        action="issue.priority_overridden" if body.band else "issue.priority_override_cleared",
        entity_type="issue",
        entity_id=issue.id,
        actor=principal,
        before=before,
        after={**after, "computed_band": issue.priority_band, "version": issue.version},
    )


async def set_category(
    db: AsyncSession, principal: Principal, issue_id: uuid.UUID, body: CategoryChange
) -> None:
    """Correct an issue's category. Its reports follow, marked as corrected
    by an operator, which makes them labels for evaluating the model."""
    current = await get_in_scope(db, principal, issue_id, permission=Permission.ISSUE_UPDATE)
    category = await db.scalar(
        select(Category).where(Category.id == body.category_id, Category.is_active.is_(True))
    )
    problem = None
    if category is None:
        problem = "Unknown or inactive category."
    elif category.id == current.category_id:
        problem = "The issue is already in this category."
    if problem or category is None:
        raise ValidationFailed(
            problem or "Invalid category.",
            details={
                "errors": [
                    {"loc": ["body", "category_id"], "msg": problem, "type": "invalid_value"}
                ]
            },
        )
    if not body.reason:
        raise ReasonRequired(details={"field": "category_id"})

    # The issue changes family: hold both matching locks so no match is
    # deciding against it meanwhile.
    await linking.lock_families(db, current.tenant_id, [current.category_id, category.id])
    issue = await _locked(db, principal, issue_id, body.version, Permission.ISSUE_UPDATE)
    old = await db.get(Category, issue.category_id)
    report_categories = {
        str(report_id): str(category_id)
        for report_id, category_id in await db.execute(
            select(Report.id, Report.category_id).where(Report.issue_id == issue.id)
        )
    }
    issue.category_id = category.id
    issue.version += 1
    await db.execute(
        update(Report)
        .where(Report.issue_id == issue.id)
        .values(category_id=category.id, category_source=CategorySource.OPERATOR)
        .execution_options(synchronize_session="fetch")
    )
    data = {"from": old.code if old else None, "to": category.code}
    db.add(_timeline(issue, EventType.CATEGORY_CHANGED, principal, body.reason, data))
    await db.flush()
    await audit.record(
        db,
        action="issue.category_changed",
        entity_type="issue",
        entity_id=issue.id,
        actor=principal,
        before={"category": data["from"], "report_categories": report_categories},
        after={"category": category.code, "reason": body.reason, "version": issue.version},
    )
    await priority.recompute(db, issue.id)
