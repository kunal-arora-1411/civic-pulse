"""Weekly matching quality rollups and drift alerts.

Everything is derived from tables that already exist: match decisions,
review tasks, reports and issue events. Each figure is anchored on the
report's creation, so a week's numbers keep filling in as staff review
and correct it; the alert job therefore looks at the latest complete
week. Alerts are log lines for people to act on; nothing here changes a
match or a category (PRD 8.6: AI never decides alone).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field, fields
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, distinct, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.tenancy import system_session
from app.domains.categories.models import Category
from app.domains.issues.models import EventType, IssueEvent
from app.domains.matching.models import (
    Decision,
    Feedback,
    MatchDecision,
    ReviewResolution,
    ReviewTask,
)
from app.domains.reports.models import CategorySource, Report

logger = logging.getLogger(__name__)

BASELINE_WEEKS = 4

Key = tuple[uuid.UUID, str]  # (tenant id, category code)


@dataclass
class WeekRollup:
    auto_linked: int = 0
    auto_link_undone: int = 0
    review_opened: int = 0
    review_linked: int = 0
    review_new_issue: int = 0
    suggested: int = 0
    corrected: int = 0

    def add(self, other: WeekRollup) -> None:
        for f in fields(self):
            setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))

    @property
    def false_merge_rate(self) -> float | None:
        return self.auto_link_undone / self.auto_linked if self.auto_linked else None

    @property
    def correction_rate(self) -> float | None:
        return self.corrected / self.suggested if self.suggested else None


@dataclass
class Alert:
    tenant_id: uuid.UUID
    category: str
    metric: str
    week: date
    rate: float
    baseline: float
    samples: int


@dataclass
class AlertRun:
    week: date
    rollups: dict[Key, WeekRollup] = field(default_factory=dict)
    alerts: list[Alert] = field(default_factory=list)


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def latest_complete_week(today: date | None = None) -> date:
    tz = ZoneInfo(get_settings().local_timezone)
    return week_start(today or datetime.now(tz).date()) - timedelta(days=7)


async def weekly_rollup(db: AsyncSession, week: date) -> dict[Key, WeekRollup]:
    """Counts per (tenant, category) for reports created in the local week
    starting on Monday `week`. The session must be able to see every
    tenant it should count (the alert job uses the system session)."""
    tz = ZoneInfo(get_settings().local_timezone)
    lo = datetime.combine(week_start(week), time.min, tzinfo=tz)
    hi = lo + timedelta(days=7)
    key_cols = (Report.tenant_id, Category.code)
    base = (
        select(*key_cols)
        .join(Category, Category.id == Report.category_id)
        .where(Report.created_at >= lo, Report.created_at < hi)
    )
    out: dict[Key, WeekRollup] = {}

    async def put(query: Any, count: Any, attr: str) -> None:
        rows: Iterable[Any] = await db.execute(query.add_columns(count).group_by(*key_cols))
        for tenant_id, code, n in rows:
            roll = out.setdefault((tenant_id, code), WeekRollup())
            setattr(roll, attr, getattr(roll, attr) + int(n))

    per_report = func.count(distinct(Report.id))
    auto = base.join(MatchDecision, MatchDecision.report_id == Report.id).where(
        MatchDecision.decision == Decision.AUTO_LINKED
    )
    await put(auto, per_report, "auto_linked")
    # Undone: staff said the link was wrong, or the report no longer sits
    # on the issue it was linked to (unlinked or split off), unless that
    # issue was itself merged away, which is consolidation, not a mistake.
    merged_away = exists().where(
        IssueEvent.issue_id == MatchDecision.candidate_issue_id,
        IssueEvent.type == EventType.MERGED_INTO,
    )
    undone = auto.where(
        or_(
            MatchDecision.feedback == Feedback.INCORRECT,
            and_(
                Report.issue_id.is_distinct_from(MatchDecision.candidate_issue_id),
                ~merged_away,
            ),
        )
    )
    await put(undone, per_report, "auto_link_undone")

    reviews = base.join(ReviewTask, ReviewTask.report_id == Report.id)
    await put(reviews, func.count(), "review_opened")
    await put(
        reviews.where(ReviewTask.resolution == ReviewResolution.LINKED),
        func.count(),
        "review_linked",
    )
    await put(
        reviews.where(ReviewTask.resolution == ReviewResolution.NEW_ISSUE),
        func.count(),
        "review_new_issue",
    )

    sources = [CategorySource.AI_ACCEPTED, CategorySource.AI_CORRECTED]
    await put(base.where(Report.category_source.in_(sources)), func.count(), "suggested")
    await put(
        base.where(Report.category_source == CategorySource.AI_CORRECTED),
        func.count(),
        "corrected",
    )
    return out


def find_alerts(
    week: date,
    current: dict[Key, WeekRollup],
    history: list[dict[Key, WeekRollup]],
    *,
    ratio: float,
    min_samples: int,
) -> list[Alert]:
    """Flag a (tenant, category) whose rate this week exceeds `ratio` times
    its pooled rate over the prior weeks. Both sides need `min_samples`,
    so a quiet category doesn't alert on one bad report."""
    alerts: list[Alert] = []
    for key in sorted(current, key=lambda k: (str(k[0]), k[1])):
        now = current[key]
        baseline = WeekRollup()
        for past in history:
            if key in past:
                baseline.add(past[key])
        for metric, n_now, n_base in (
            ("false_merge_rate", now.auto_linked, baseline.auto_linked),
            ("correction_rate", now.suggested, baseline.suggested),
        ):
            rate, base_rate = getattr(now, metric), getattr(baseline, metric)
            if n_now < min_samples or n_base < min_samples:
                continue
            if (
                rate is not None
                and base_rate is not None
                and rate > base_rate * ratio
                and rate > base_rate
            ):
                alerts.append(Alert(key[0], key[1], metric, week, rate, base_rate, n_now))
    return alerts


async def check_latest_week(today: date | None = None) -> AlertRun:
    settings = get_settings()
    week = latest_complete_week(today)
    async with system_session(reason="matching quality monitoring") as db:
        current = await weekly_rollup(db, week)
        history = [
            await weekly_rollup(db, week - timedelta(days=7 * n))
            for n in range(1, BASELINE_WEEKS + 1)
        ]
    run = AlertRun(week=week, rollups=current)
    run.alerts = find_alerts(
        week,
        current,
        history,
        ratio=settings.quality_alert_ratio,
        min_samples=settings.quality_alert_min_samples,
    )
    for alert in run.alerts:
        logger.warning(
            "matching quality alert: %s for %s rose to %.2f (baseline %.2f)",
            alert.metric,
            alert.category,
            alert.rate,
            alert.baseline,
            extra={
                "event": "matching_quality_alert",
                "tenant_id": str(alert.tenant_id),
                "category": alert.category,
                "metric": alert.metric,
                "week": alert.week.isoformat(),
                "rate": round(alert.rate, 4),
                "baseline": round(alert.baseline, 4),
                "samples": alert.samples,
                "ratio": settings.quality_alert_ratio,
            },
        )
    return run
