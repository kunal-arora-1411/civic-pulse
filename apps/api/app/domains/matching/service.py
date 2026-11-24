"""Duplicate matching for one report (contract D.1 and D.2).

`process_report` is the `match_report` task. First, outside any lock, it
makes sure the report's photos have embeddings (computing missing ones
needs the model). Then `decide_and_apply` runs in **one transaction that
holds the advisory lock for (tenant, category family)**: it re-reads the
report under a row lock, finds and scores the candidates, records a match
decision for every candidate, and links the report, opens a review task or
creates an issue. Because candidates are searched after the lock is taken,
a concurrent duplicate either committed its issue already (and is seen as
a candidate) or waits for this transaction to finish (FR-036).

Re-running for a report that is no longer pending does nothing, so task
retries and redelivery are safe.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session_factory
from app.core.logging import log_fields
from app.core.tenancy import set_tenant, system_session
from app.domains.ai.analysis import AIUnavailable, ensure_embeddings
from app.domains.ai.models import Classification, ClassificationStatus, ModelRegistryEntry
from app.domains.audit import service as audit
from app.domains.categories.models import Category
from app.domains.config.schemas import MatchingConfig
from app.domains.config.service import matching_config
from app.domains.geo.distance import degree_margin
from app.domains.matching import linking, scoring
from app.domains.matching.models import Decision, MatchDecision, ReviewTask
from app.domains.matching.scoring import (
    CATEGORY_SAME,
    CATEGORY_SIBLING,
    Measurements,
    Outcome,
    VisualReason,
    decide,
    signals_json,
)
from app.domains.media.models import MediaAsset
from app.domains.priority import service as priority
from app.domains.reports.models import MatchingStatus, Report
from app.domains.workflow.statuses import IssueStatus

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 10
CLOSED_STATUSES = (IssueStatus.RESOLVED, IssueStatus.REJECTED, IssueStatus.CLOSED)
# Before the fallback deadline, wait this long between attempts to get
# embeddings for the report's photos.
RETRY_SECONDS = 15


@dataclass(slots=True)
class MatchOutcome:
    status: str  # an Outcome value, "already_decided", or "retry"
    issue_id: uuid.UUID | None = None
    retry_in: int | None = None
    fallback: bool = False


# --- candidates ---------------------------------------------------------------------------


async def compatible_categories(db: AsyncSession, category: Category) -> dict[uuid.UUID, float]:
    """Category id -> compatibility: the same category 1.0; its parent, its
    children and its siblings 0.5. Anything else is not a candidate."""
    conditions = [Category.id == category.id, Category.parent_id == category.id]
    if category.parent_id is not None:
        conditions += [Category.id == category.parent_id, Category.parent_id == category.parent_id]
    rows = await db.scalars(select(Category.id).where(or_(*conditions)))
    return {
        category_id: CATEGORY_SAME if category_id == category.id else CATEGORY_SIBLING
        for category_id in rows
    }


_CANDIDATES = text(
    """
    WITH point AS (SELECT location FROM reports WHERE id = :report_id)
    SELECT i.id,
           i.category_id,
           ST_Distance(geography(i.location), geography(point.location)) AS distance_m,
           coalesce((SELECT max(r.created_at) FROM reports r WHERE r.issue_id = i.id),
                    i.created_at) AS last_report_at
    FROM civic_issues i, point
    WHERE i.tenant_id = :tenant_id
      AND i.merged_into_id IS NULL
      AND i.category_id = ANY(:categories)
      AND ST_DWithin(i.location, point.location, :degrees)
      AND ST_DWithin(geography(i.location), geography(point.location), :radius)
      AND (i.status <> ALL(:closed) OR i.status_changed_at >= :window_start)
    ORDER BY distance_m, i.id
    LIMIT :limit
    """
)

# Best cosine similarity and smallest pHash distance between any photo of
# the report and any photo on each candidate issue, for one model.
_VISUAL = text(
    """
    SELECT r.issue_id,
           max(1 - (a.embedding <=> b.embedding)) AS cosine,
           min(bit_count((a.phash # b.phash)::bit(64))) AS hamming
    FROM media_embeddings a
    JOIN media_assets ma ON ma.id = a.media_id
    JOIN media_embeddings b ON b.model_id = a.model_id
    JOIN media_assets mb ON mb.id = b.media_id
    JOIN reports r ON r.id = mb.report_id
    WHERE ma.report_id = :report_id
      AND a.model_id = :model_id
      AND r.issue_id = ANY(:issues)
    GROUP BY r.issue_id
    """
)

_REPORT_MODEL = text(
    """
    SELECT e.model_id, count(*) AS n
    FROM media_embeddings e JOIN media_assets m ON m.id = e.media_id
    WHERE m.report_id = :report_id
    GROUP BY e.model_id
    ORDER BY count(*) DESC, max(e.created_at) DESC
    LIMIT 1
    """
)


async def embedded_count(
    db: AsyncSession, report_id: uuid.UUID, model_id: str | None
) -> tuple[str | None, int]:
    """(model, how many of the report's photos it has embedded): the given
    model, or else whichever model has embedded the most of them."""
    if model_id is None:
        row = (await db.execute(_REPORT_MODEL, {"report_id": report_id})).first()
        return (row[0], int(row[1])) if row else (None, 0)
    count = await db.scalar(
        text(
            "SELECT count(*) FROM media_embeddings e JOIN media_assets m ON m.id = e.media_id "
            "WHERE m.report_id = :report_id AND e.model_id = :model_id"
        ),
        {"report_id": report_id, "model_id": model_id},
    )
    return model_id, int(count or 0)


async def measure_candidates(
    db: AsyncSession,
    report: Report,
    category: Category,
    *,
    lat: float,
    model_id: str | None,
    fallback: bool,
    has_photos: bool,
) -> list[tuple[uuid.UUID, Measurements]]:
    compatible = await compatible_categories(db, category)
    radius = float(category.dedup_radius_m)
    window = float(category.dedup_window_days)
    rows = (
        await db.execute(
            _CANDIDATES,
            {
                "report_id": report.id,
                "tenant_id": report.tenant_id,
                "categories": list(compatible),
                "degrees": degree_margin(radius, lat),
                "radius": radius,
                "closed": [s.value for s in CLOSED_STATUSES],
                "window_start": report.created_at - timedelta(days=window),
                "limit": MAX_CANDIDATES,
            },
        )
    ).all()
    visual: dict[uuid.UUID, tuple[float, int]] = {}
    if rows and has_photos and model_id and not fallback:
        visual = {
            issue_id: (float(cosine), int(hamming))
            for issue_id, cosine, hamming in await db.execute(
                _VISUAL,
                {"report_id": report.id, "model_id": model_id, "issues": [r[0] for r in rows]},
            )
        }
    measured = []
    for issue_id, category_id, distance, last_report_at in rows:
        cosine, hamming = visual.get(issue_id, (None, None))
        age = (report.created_at - last_report_at).total_seconds() / 86400
        measured.append(
            (
                issue_id,
                Measurements(
                    distance_m=float(distance),
                    radius_m=radius,
                    age_days=max(0.0, age),
                    window_days=window,
                    category=compatible[category_id],
                    best_cosine=cosine,
                    min_phash_distance=hamming,
                    visual_reason=None if has_photos else VisualReason.NO_PHOTOS,
                ),
            )
        )
    return measured


# --- deciding -------------------------------------------------------------------------------


async def model_visual_floor(db: AsyncSession, model_id: str | None) -> float | None:
    """The auto-link visual floor measured for this model, from its registry
    metrics (`matching.visual_min`), or None when none was recorded."""
    if model_id is None:
        return None
    metrics = await db.scalar(
        select(ModelRegistryEntry.metrics).where(ModelRegistryEntry.id == model_id)
    )
    value = ((metrics or {}).get("matching") or {}).get("visual_min")
    return float(value) if isinstance(value, int | float) else None


async def decide_and_apply(
    report_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    model_id: str | None,
    fallback: bool,
    now: datetime | None = None,
) -> MatchOutcome:
    now = now or datetime.now(UTC)
    async with get_session_factory()() as db:
        await set_tenant(db, tenant_id)
        category_id = await db.scalar(select(Report.category_id).where(Report.id == report_id))
        if category_id is None:
            return MatchOutcome("already_decided")
        await linking.lock_families(db, tenant_id, [category_id])
        report = await db.scalar(
            select(Report)
            .where(Report.id == report_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if report is None or report.matching_status != MatchingStatus.PENDING:
            await db.rollback()
            return MatchOutcome("already_decided")

        # Similarity scales differ between models, so unless the tenant set
        # its own, the visual floor is the one measured for this model.
        config = (await matching_config(db)).with_visual_floor(
            await model_visual_floor(db, model_id)
        )
        category = await db.get(Category, report.category_id)
        assert category is not None
        lat = float(
            await db.scalar(
                text("SELECT ST_Y(location) FROM reports WHERE id = :id"), {"id": report.id}
            )
        )
        photos = await db.scalar(
            select(MediaAsset.id).where(MediaAsset.report_id == report.id).limit(1)
        )
        candidates = await measure_candidates(
            db,
            report,
            category,
            lat=lat,
            model_id=model_id,
            fallback=fallback,
            has_photos=photos is not None,
        )
        decision = decide(candidates, config, fallback=fallback)

        issue_id = await _apply(
            db, report, decision, config, model_id=model_id, fallback=fallback, now=now
        )
        await audit.record(
            db,
            action="report.matched",
            entity_type="report",
            entity_id=report.id,
            after={
                "decision": decision.outcome.value,
                "issue_id": str(issue_id) if issue_id else None,
                "fallback": fallback,
                "model_id": None if fallback else model_id,
                "candidates": [
                    {"issue_id": str(s.key), "score": round(s.score, 4)} for s in decision.ranked
                ],
            },
        )
        await db.commit()
    logger.info(
        "report matched",
        extra=log_fields(
            report_id=str(report_id), decision=decision.outcome.value, fallback=fallback
        ),
    )
    return MatchOutcome(decision.outcome.value, issue_id=issue_id, fallback=fallback)


async def _apply(
    db: AsyncSession,
    report: Report,
    decision: scoring.Decision[uuid.UUID],
    config: MatchingConfig,
    *,
    model_id: str | None,
    fallback: bool,
    now: datetime,
) -> uuid.UUID | None:
    outcome: Outcome = decision.outcome
    chosen = decision.chosen.key if decision.chosen else None
    for rank, scored in enumerate(decision.ranked, start=1):
        if outcome is Outcome.REVIEW:
            kind = Decision.SENT_TO_REVIEW
        elif scored.key == chosen:
            kind = Decision.AUTO_LINKED
        else:
            kind = Decision.REJECTED_CANDIDATE
        db.add(
            MatchDecision(
                tenant_id=report.tenant_id,
                report_id=report.id,
                candidate_issue_id=scored.key,
                rank=rank,
                score=round(scored.score, 6),
                signals=signals_json(scored, config, fallback=fallback),
                decision=kind,
                model_id=None if fallback else model_id,
                decided_at=now,
            )
        )
    await db.flush()

    if outcome is Outcome.AUTO_LINK:
        assert chosen is not None
        issues = await linking.lock_issues(db, [chosen])
        await linking.link_report(db, report, issues[chosen], actor=None, reason="auto_linked")
        return chosen
    if outcome is Outcome.REVIEW:
        report.matching_status = MatchingStatus.REVIEW
        db.add(ReviewTask(tenant_id=report.tenant_id, report_id=report.id))
        await db.flush()
        await audit.record(
            db,
            action="review_task.opened",
            entity_type="report",
            entity_id=report.id,
            after={"candidates": [str(s.key) for s in decision.ranked], "fallback": fallback},
        )
        return None
    issue = await linking.create_issue_for_report(db, report, actor=None, reason="no_match")
    return issue.id


# --- the task --------------------------------------------------------------------------------


async def process_report(
    report_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    allow_model: bool = True,
    now: datetime | None = None,
) -> MatchOutcome:
    """Match one report. With `allow_model`, missing embeddings are computed
    first (the AI worker); without it, only stored ones are used (the
    watchdog on the default worker).

    Photos with no embeddings yet: retry later, until the report is older
    than MATCHING_FALLBACK_AFTER_SECONDS; then match without the visual
    signal. StorageError propagates for the task to retry.
    """
    now = now or datetime.now(UTC)
    async with get_session_factory()() as db:
        await set_tenant(db, tenant_id)
        report = await db.scalar(select(Report).where(Report.id == report_id))
        if report is None or report.matching_status != MatchingStatus.PENDING:
            return MatchOutcome("already_decided")
        created_at = report.created_at
        media_ids = list(
            await db.scalars(select(MediaAsset.id).where(MediaAsset.report_id == report_id))
        )
        await db.commit()

        model_id: str | None = None
        fallback = False
        if media_ids:
            if allow_model:
                try:
                    model_id = await ensure_embeddings(tenant_id, media_ids)
                except AIUnavailable as exc:
                    logger.warning(
                        "matching without fresh embeddings",
                        extra=log_fields(report_id=str(report_id), error=str(exc)),
                    )
            model_id, embedded = await embedded_count(db, report_id, model_id)
            await db.commit()
            if embedded == 0:
                deadline = created_at + timedelta(
                    seconds=get_settings().matching_fallback_after_seconds
                )
                if now < deadline:
                    wait = math.ceil((deadline - now).total_seconds())
                    return MatchOutcome("retry", retry_in=max(1, min(RETRY_SECONDS, wait)))
                fallback = True

    return await decide_and_apply(
        report_id, tenant_id, model_id=model_id, fallback=fallback, now=now
    )


# --- the watchdog ----------------------------------------------------------------------------


@dataclass
class WatchdogResult:
    requeue: list[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=list)
    decided: int = 0
    failed_classifications: int = 0
    priorities: int = 0

    def summary(self) -> dict[str, int]:
        return {
            "requeued": len(self.requeue),
            "decided": self.decided,
            "failed_classifications": self.failed_classifications,
            "priorities": self.priorities,
        }


REQUEUE_AFTER = timedelta(seconds=60)


async def watchdog(*, now: datetime | None = None) -> WatchdogResult:
    """Keep the pipeline moving when messages are lost or the AI is down.

    * Reports pending for a minute are queued again (the message may have
      been lost, or the broker was down when the report was saved).
    * Reports pending past the fallback deadline are matched here and now
      with whatever embeddings exist; with none, without the visual signal,
      so they never auto-link.
    * Classifications nobody picked up are failed (`ai_unavailable`).
    * Issues whose priority was never computed get computed.
    """
    now = now or datetime.now(UTC)
    settings = get_settings()
    result = WatchdogResult()
    deadline = now - timedelta(seconds=settings.matching_fallback_after_seconds)
    async with system_session(reason="matching watchdog: stuck reports") as db:
        stuck = (
            await db.execute(
                select(Report.id, Report.tenant_id, Report.created_at)
                .where(
                    Report.matching_status == MatchingStatus.PENDING,
                    Report.created_at < now - REQUEUE_AFTER,
                )
                .order_by(Report.created_at)
                .limit(500)
            )
        ).all()
        timeout = now - timedelta(seconds=settings.ai_classification_timeout_seconds)
        failed = await db.execute(
            update(Classification)
            .where(
                Classification.status == ClassificationStatus.PENDING,
                Classification.created_at < timeout,
            )
            .values(status=ClassificationStatus.FAILED, error="ai_unavailable", completed_at=now)
        )
        result.failed_classifications = int(failed.rowcount or 0)  # pyright: ignore[reportAttributeAccessIssue]

    for report_id, tenant_id, created_at in stuck:
        if created_at >= deadline:
            result.requeue.append((report_id, tenant_id))
            continue
        try:
            outcome = await process_report(report_id, tenant_id, allow_model=False, now=now)
        except Exception:
            logger.exception(
                "watchdog could not match a report", extra=log_fields(report_id=str(report_id))
            )
            continue
        result.decided += outcome.status not in ("already_decided", "retry")

    result.priorities = await priority.recompute_never_computed()
    logger.info("matching watchdog finished", extra=log_fields(**result.summary()))
    return result
