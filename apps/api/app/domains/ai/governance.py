"""Model registry and AI quality counts for administrators (contract G)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import and_, distinct, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.ai.models import Classification, ClassificationStatus, ModelRegistryEntry
from app.domains.categories.models import Category
from app.domains.matching.models import Decision, Feedback, MatchDecision, ReviewTask
from app.domains.reports.models import CategorySource, MatchingStatus, Report

DEFAULT_WINDOW_DAYS = 30


class ModelOut(BaseModel):
    model_id: str
    task: str
    name: str
    version: str
    source: str | None
    license: str | None
    deployed_at: datetime
    intended_use: str | None
    metrics: dict[str, Any]
    active: bool = Field(description="The most recently deployed model for its task.")


class ModelList(BaseModel):
    items: list[ModelOut] = Field(description="Newest deployment first.")


async def list_models(db: AsyncSession) -> ModelList:
    rows = list(
        await db.scalars(
            select(ModelRegistryEntry).order_by(
                ModelRegistryEntry.deployed_at.desc(), ModelRegistryEntry.id
            )
        )
    )
    active: dict[str, str] = {}
    for row in rows:  # newest first, so the first per task wins
        active.setdefault(row.task, row.id)
    return ModelList(
        items=[
            ModelOut(
                model_id=row.id,
                task=row.task,
                name=row.name,
                version=row.version,
                source=row.source,
                license=row.license,
                deployed_at=row.deployed_at,
                intended_use=row.intended_use,
                metrics=row.metrics or {},
                active=active[row.task] == row.id,
            )
            for row in rows
        ]
    )


class ClassificationCounts(BaseModel):
    done: int
    failed: int
    accepted_by_category: dict[str, int] = Field(
        description="Reports whose citizen kept the top suggestion, by category code."
    )
    corrected_by_category: dict[str, int] = Field(
        description="Reports whose citizen chose another category, by the chosen code."
    )


class MatchingCounts(BaseModel):
    auto_linked: int
    sent_to_review: int
    new_issue: int = Field(description="Started a new issue without a review.")


class ReviewCounts(BaseModel):
    linked: int
    new_issue: int


class FeedbackCounts(BaseModel):
    correct: int
    incorrect: int


class QualityOut(BaseModel):
    from_: date = Field(alias="from", serialization_alias="from")
    to: date
    classifications: ClassificationCounts
    matching: MatchingCounts
    reviews: ReviewCounts
    auto_link_feedback: FeedbackCounts

    model_config = {"populate_by_name": True}


def default_window(today: date | None = None) -> tuple[date, date]:
    tz = ZoneInfo(get_settings().local_timezone)
    end = today or datetime.now(tz).date()
    return end - timedelta(days=DEFAULT_WINDOW_DAYS - 1), end


async def quality(db: AsyncSession, start: date, end: date) -> QualityOut:
    """Counts over whole days [start, end] in the local time zone. Each
    figure is anchored on its own event: classifications and reports by
    creation, reviews by resolution, feedback by when it was given."""
    tz = ZoneInfo(get_settings().local_timezone)
    lo = datetime.combine(start, time.min, tzinfo=tz)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)

    statuses = dict(
        (
            await db.execute(
                select(Classification.status, func.count())
                .where(Classification.created_at >= lo, Classification.created_at < hi)
                .group_by(Classification.status)
            )
        ).all()
    )
    by_category: dict[str, dict[str, int]] = {
        CategorySource.AI_ACCEPTED: {},
        CategorySource.AI_CORRECTED: {},
    }
    for source, code, count in await db.execute(
        select(Report.category_source, Category.code, func.count())
        .join(Category, Category.id == Report.category_id)
        .where(
            Report.created_at >= lo,
            Report.created_at < hi,
            Report.category_source.in_(list(by_category)),
        )
        .group_by(Report.category_source, Category.code)
    ):
        by_category[source][code] = int(count)

    reported = and_(Report.created_at >= lo, Report.created_at < hi)
    auto_linked = await db.scalar(
        select(func.count(distinct(MatchDecision.report_id)))
        .join(Report, Report.id == MatchDecision.report_id)
        .where(reported, MatchDecision.decision == Decision.AUTO_LINKED)
    )
    sent_to_review = await db.scalar(
        select(func.count())
        .select_from(ReviewTask)
        .join(Report, Report.id == ReviewTask.report_id)
        .where(reported)
    )
    new_issue = await db.scalar(
        select(func.count())
        .select_from(Report)
        .where(
            reported,
            Report.matching_status == MatchingStatus.NEW_ISSUE,
            ~exists().where(ReviewTask.report_id == Report.id),
        )
    )
    reviews = dict(
        (
            await db.execute(
                select(ReviewTask.resolution, func.count())
                .where(ReviewTask.resolved_at >= lo, ReviewTask.resolved_at < hi)
                .group_by(ReviewTask.resolution)
            )
        ).all()
    )
    feedback = dict(
        (
            await db.execute(
                select(MatchDecision.feedback, func.count())
                .where(
                    MatchDecision.decision == Decision.AUTO_LINKED,
                    MatchDecision.feedback_at >= lo,
                    MatchDecision.feedback_at < hi,
                )
                .group_by(MatchDecision.feedback)
            )
        ).all()
    )
    counts = {
        "classifications": ClassificationCounts(
            done=int(statuses.get(ClassificationStatus.DONE, 0)),
            failed=int(statuses.get(ClassificationStatus.FAILED, 0)),
            accepted_by_category=by_category[CategorySource.AI_ACCEPTED],
            corrected_by_category=by_category[CategorySource.AI_CORRECTED],
        ),
        "matching": MatchingCounts(
            auto_linked=int(auto_linked or 0),
            sent_to_review=int(sent_to_review or 0),
            new_issue=int(new_issue or 0),
        ),
        "reviews": ReviewCounts(
            linked=int(reviews.get("linked", 0)), new_issue=int(reviews.get("new_issue", 0))
        ),
        "auto_link_feedback": FeedbackCounts(
            correct=int(feedback.get(Feedback.CORRECT, 0)),
            incorrect=int(feedback.get(Feedback.INCORRECT, 0)),
        ),
    }
    # "from" is a Python keyword, so the field is filled through its alias.
    return QualityOut.model_validate({"from": start, "to": end, **counts})
