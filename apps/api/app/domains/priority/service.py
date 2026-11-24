"""Keeping each issue's severity and priority current.

`recompute()` gathers the facts for one issue, runs the pure rules from
app/domains/priority/rules.py and stores the result, inside the caller's
transaction. It is called on every trigger the contract lists: a report
linked or moved (matching, review, merge, split), a severity or category
change, a status change. The batch functions below cover ageing (nightly),
config changes and issues that have never been computed.

Recomputing is not an edit by anyone: it leaves `version` and `updated_at`
alone, so a nightly run never makes a colleague's open page stale.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.db import get_session_factory
from app.core.logging import log_fields
from app.core.tenancy import set_tenant, system_session
from app.domains.categories.models import Category
from app.domains.community.models import IssueSupport
from app.domains.config.service import priority_config
from app.domains.geo.distance import distance_meters, within_meters
from app.domains.issues.models import CivicIssue, SeveritySource
from app.domains.places.models import PlaceOfInterest
from app.domains.priority.rules import (
    NEAR_PLACES_RADIUS_M,
    PriorityInputs,
    SeverityInputs,
    SeverityLevel,
    SeverityRules,
    compute_priority,
    compute_severity,
)
from app.domains.reports.models import Report, ReportStatus
from app.domains.workflow.statuses import IssueStatus

logger = logging.getLogger(__name__)

# Statuses whose issues need no attention: they score 0 (contract F).
INACTIVE_STATUSES = frozenset({IssueStatus.REJECTED, IssueStatus.CLOSED})
_BATCH = 200


def severity_rules(category: Category) -> SeverityRules:
    if not category.severity_rules:
        return SeverityRules()
    try:
        return SeverityRules.model_validate(category.severity_rules)
    except ValidationError as exc:  # stored before a rule format change
        logger.error(
            "invalid severity rules; using the default",
            extra=log_fields(category_id=str(category.id), error=str(exc)),
        )
        return SeverityRules()


async def recompute(db: AsyncSession, issue_id: uuid.UUID, *, now: datetime | None = None) -> None:
    """Recompute and store one issue's severity and priority.

    The caller's session must be scoped to the issue's tenant. Callers that
    are changing the issue hold its row lock already; others may race a
    concurrent change harmlessly, because whoever commits last computed
    from the state they saw and the next trigger corrects it.
    """
    now = now or datetime.now(UTC)
    await db.flush()  # the caller's changes count (reports moved, status...)
    row = (
        await db.execute(
            select(CivicIssue, func.ST_Y(CivicIssue.location))
            .where(CivicIssue.id == issue_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if row is None:
        return
    issue, lat = row[0], float(row[1])
    location = select(CivicIssue.location).where(CivicIssue.id == issue_id).scalar_subquery()

    category = await db.scalar(
        select(Category)
        .where(Category.id == issue.category_id)
        .execution_options(populate_existing=True)
    )
    assert category is not None
    rules = severity_rules(category)

    reports = (
        await db.execute(
            select(Report.details, Report.reporter_id).where(
                Report.issue_id == issue.id, Report.status == ReportStatus.ACCEPTED
            )
        )
    ).all()
    reporter_ids = {reporter for _, reporter in reports}
    unique_reporters = len(reporter_ids)
    # Supporters who also reported are already counted as reporters.
    supporter_ids = set(
        await db.scalars(select(IssueSupport.user_id).where(IssueSupport.issue_id == issue.id))
    )
    supporters = len(supporter_ids - reporter_ids)

    radius = rules.search_radius_m
    nearest = {
        kind: float(distance)
        for kind, distance in await db.execute(
            select(PlaceOfInterest.kind, func.min(distance_meters(PlaceOfInterest.geom, location)))
            .where(within_meters(PlaceOfInterest.geom, location, radius, lat=lat))
            .group_by(PlaceOfInterest.kind)
        )
    }

    values: dict[str, Any] = {}
    if issue.severity_source == SeveritySource.OVERRIDE:
        level = SeverityLevel(issue.severity)
    else:
        result = compute_severity(
            rules,
            SeverityInputs(
                details=[details or {} for details, _ in reports],
                nearest_place_m=nearest,
                unique_reporters=unique_reporters,
            ),
        )
        level = result.level
        values |= {"severity": level.value, "severity_reason": result.reason}

    config = await priority_config(db)
    other = aliased(CivicIssue)
    recurrence = await db.scalar(
        select(func.count())
        .select_from(other)
        .where(
            other.category_id == issue.category_id,
            other.id != issue.id,
            other.merged_into_id.is_(None),
            other.created_at >= now - timedelta(days=config.recurrence.lookback_days),
            within_meters(other.location, location, config.recurrence.radius_m, lat=lat),
        )
    )

    inactive: str | None = None
    if issue.merged_into_id is not None:
        inactive = "merged"
    elif issue.status in INACTIVE_STATUSES:
        inactive = issue.status
    priority = compute_priority(
        config,
        PriorityInputs(
            severity=level,
            unique_reporters=unique_reporters,
            age_days=(now - issue.created_at).total_seconds() / 86400,
            recurrence=int(recurrence or 0),
            near_place=any(d <= NEAR_PLACES_RADIUS_M for d in nearest.values()),
            inactive_status=inactive,
            supporters=supporters,
        ),
    )
    values |= {
        "priority_score": priority.score,
        "priority_band": priority.band.value,
        "priority_factors": [f.as_json() for f in priority.factors],
        "priority_computed_at": now,
        # Not an edit: keep the timestamp people sort and reload by.
        "updated_at": CivicIssue.updated_at,
    }
    await db.execute(
        update(CivicIssue)
        .where(CivicIssue.id == issue.id)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    # Bring the in-session copy up to date for whoever renders it next.
    await db.refresh(issue)


async def _recompute_in_own_transaction(issue_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
    """For batch jobs: one short transaction per issue, skipping an issue
    someone is changing right now (their change recomputes it anyway)."""
    async with get_session_factory()() as db:
        await set_tenant(db, tenant_id)
        locked = await db.scalar(
            select(CivicIssue.id).where(CivicIssue.id == issue_id).with_for_update(skip_locked=True)
        )
        if locked is None:
            await db.rollback()
            return False
        await recompute(db, issue_id)
        await db.commit()
        return True


async def _recompute_rows(rows: Sequence[Any]) -> int:
    done = 0
    for issue_id, tenant_id in rows:
        try:
            done += await _recompute_in_own_transaction(issue_id, tenant_id)
        except Exception:
            # One bad issue must not stop the batch; it is logged and the
            # next run tries again.
            logger.exception("priority recompute failed", extra=log_fields(issue_id=str(issue_id)))
    return done


async def recompute_never_computed(*, limit: int = _BATCH) -> int:
    """Issues with no priority yet (new from a migration or a crash)."""
    async with system_session(reason="priority: issues never computed") as db:
        rows = (
            await db.execute(
                select(CivicIssue.id, CivicIssue.tenant_id)
                .where(CivicIssue.priority_computed_at.is_(None))
                .order_by(CivicIssue.created_at)
                .limit(limit)
            )
        ).all()
    return await _recompute_rows(rows)


async def recompute_tenant(tenant_id: uuid.UUID, *, category_id: uuid.UUID | None = None) -> int:
    """Every live issue of a tenant (or one category), after a rule change."""
    async with get_session_factory()() as db:
        await set_tenant(db, tenant_id)
        stmt = select(CivicIssue.id, CivicIssue.tenant_id).where(
            CivicIssue.merged_into_id.is_(None)
        )
        if category_id is not None:
            stmt = stmt.where(CivicIssue.category_id == category_id)
        rows = (await db.execute(stmt.order_by(CivicIssue.id))).all()
    return await _recompute_rows(rows)


async def recompute_all() -> int:
    """The nightly run: age moves every open issue's score, in every tenant."""
    done, after = 0, uuid.UUID(int=0)
    while True:
        async with system_session(reason="priority: nightly recompute") as db:
            rows = (
                await db.execute(
                    select(CivicIssue.id, CivicIssue.tenant_id)
                    .where(CivicIssue.merged_into_id.is_(None), CivicIssue.id > after)
                    .order_by(CivicIssue.id)
                    .limit(_BATCH)
                )
            ).all()
        if not rows:
            return done
        done += await _recompute_rows(rows)
        after = rows[-1][0]
