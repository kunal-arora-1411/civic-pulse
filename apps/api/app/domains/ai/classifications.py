"""Category suggestions while a citizen reports (FR-020 to FR-022).

The request stores a `pending` classification, commits it, queues the AI
task and then waits a bounded time (4 s by default) for the result by
re-reading the row. Polling the row rather than waiting on a Celery result:
the row is what GET returns anyway, so there is one source of truth; it
works whichever worker runs the task (the AI worker is a separate image)
and needs nothing from the result backend; and the cost is bounded, a
handful of primary-key reads per request with a short pause between them.

Whatever goes wrong with the AI ends in `failed` with `ai_unavailable`,
never an error response: the client then simply asks the citizen to pick
a category. A classification nobody picked up is failed on read once it
is older than AI_CLASSIFICATION_TIMEOUT_SECONDS, and by the watchdog.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import registry
from app.core.config import get_settings
from app.core.db import get_session_factory
from app.core.errors import NotFound
from app.core.logging import log_fields
from app.core.tenancy import set_tenant
from app.domains.ai.analysis import AIUnavailable, ensure_embeddings
from app.domains.ai.models import Classification, ClassificationStatus
from app.domains.ai.schemas import ClassificationCreate, ClassificationOut, Suggestion
from app.domains.ai.vision import category_prompts, default_prompts
from app.domains.categories.models import Category
from app.domains.config.service import matching_config
from app.domains.media.models import MediaAsset, MediaPurpose, MediaStatus
from app.domains.rbac.principal import Principal
from app.domains.reports.errors import InvalidMedia
from app.jobs import Jobs

logger = logging.getLogger(__name__)

NOT_CIVIC = "not_civic"
UNKNOWN = "unknown"
AI_UNAVAILABLE = "ai_unavailable"
MAX_SUGGESTIONS = 3
_USABLE = (MediaStatus.PROCESSING, MediaStatus.READY)


async def _check_media(
    db: AsyncSession, principal: Principal, media_ids: Sequence[uuid.UUID]
) -> None:
    found = {
        asset.id: asset
        for asset in await db.scalars(select(MediaAsset).where(MediaAsset.id.in_(media_ids)))
    }
    invalid: list[dict[str, str]] = []
    for media_id in media_ids:
        asset = found.get(media_id)
        if asset is None or asset.owner_id != principal.user_id:
            invalid.append({"id": str(media_id), "reason": "not_found"})
        elif asset.purpose != MediaPurpose.REPORT_EVIDENCE:
            invalid.append({"id": str(media_id), "reason": "wrong_purpose"})
        elif asset.status not in _USABLE:
            reason = "failed" if asset.status == MediaStatus.FAILED else "not_completed"
            invalid.append({"id": str(media_id), "reason": reason})
    if invalid:
        raise InvalidMedia(details={"media": invalid})


async def _fail(db: AsyncSession, classification_id: uuid.UUID, error: str) -> None:
    await db.execute(
        update(Classification)
        .where(
            Classification.id == classification_id,
            Classification.status == ClassificationStatus.PENDING,
        )
        .values(status=ClassificationStatus.FAILED, error=error, completed_at=datetime.now(UTC))
    )


async def request(
    db: AsyncSession, jobs: Jobs, principal: Principal, body: ClassificationCreate
) -> uuid.UUID:
    """Store, queue and briefly wait for a classification; returns its id."""
    assert principal.tenant_id is not None
    await _check_media(db, principal, body.media_ids)
    classification = Classification(
        id=uuid.uuid4(),
        tenant_id=principal.tenant_id,
        requested_by=principal.user_id,
        media_ids=list(body.media_ids),
        status=ClassificationStatus.PENDING,
    )
    db.add(classification)
    # Deliberate commit inside a request: the worker must be able to read
    # the row while this request is still waiting for its result.
    await db.commit()

    if not await jobs.classify(classification.id, principal.tenant_id):
        await _fail(db, classification.id, AI_UNAVAILABLE)
        await db.commit()
        return classification.id

    deadline = time.monotonic() + get_settings().ai_classification_wait_seconds
    pause = 0.05
    while True:
        status = await db.scalar(
            select(Classification.status).where(Classification.id == classification.id)
        )
        await db.commit()  # end the read so the next one sees new commits
        if status != ClassificationStatus.PENDING or time.monotonic() >= deadline:
            return classification.id
        await asyncio.sleep(min(pause, max(0.0, deadline - time.monotonic())))
        pause = min(pause * 2, 0.4)


async def suggestions_for(db: AsyncSession, classification: Classification) -> list[Suggestion]:
    """The stored scores mapped onto the tenant's active categories."""
    if classification.status != ClassificationStatus.DONE or not classification.scores:
        return []
    active = {
        c.code: c.id for c in await db.scalars(select(Category).where(Category.is_active.is_(True)))
    }
    out = [
        Suggestion(category_id=active[s["code"]], code=s["code"], confidence=s["confidence"])
        for s in classification.scores
        if s["code"] in active
    ]
    out.sort(key=lambda s: -s.confidence)
    return out[:MAX_SUGGESTIONS]


async def to_out(db: AsyncSession, classification: Classification) -> ClassificationOut:
    suggestions = await suggestions_for(db, classification)
    threshold = (await matching_config(db)).classification_threshold
    done = classification.status == ClassificationStatus.DONE
    return ClassificationOut(
        id=classification.id,
        status=ClassificationStatus(classification.status),
        model_id=classification.model_id,
        suggestions=suggestions,
        not_civic=done and classification.top_code == NOT_CIVIC,
        needs_manual=(
            not done
            or classification.top_code == UNKNOWN
            or not suggestions
            or suggestions[0].confidence < threshold
        ),
        error=classification.error,
        created_at=classification.created_at,
    )


async def get_own(
    db: AsyncSession, principal: Principal, classification_id: uuid.UUID
) -> Classification:
    """The caller's classification (404 for anyone else's), failing it
    first if it has waited too long for an AI worker."""
    classification = await db.scalar(
        select(Classification)
        .where(Classification.id == classification_id)
        .execution_options(populate_existing=True)
    )
    if classification is None or classification.requested_by != principal.user_id:
        raise NotFound()
    timeout = timedelta(seconds=get_settings().ai_classification_timeout_seconds)
    if (
        classification.status == ClassificationStatus.PENDING
        and classification.created_at < datetime.now(UTC) - timeout
    ):
        await _fail(db, classification.id, AI_UNAVAILABLE)
        await db.refresh(classification)
    return classification


# --- the AI task ---------------------------------------------------------------------------


def _parse_vector(value: str) -> list[float]:
    return [float(v) for v in value.strip("[]").split(",")]


async def run(classification_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    """The `classify` task. Idempotent: anything not pending is left alone.
    Storage errors propagate so the task retries."""
    async with get_session_factory()() as db:
        await set_tenant(db, tenant_id)
        classification = await db.scalar(
            select(Classification).where(Classification.id == classification_id)
        )
        if classification is None or classification.status != ClassificationStatus.PENDING:
            return classification.status if classification else "missing"
        media_ids = list(classification.media_ids)
        await db.commit()

        try:
            # StorageError is left to propagate: the task retries it.
            model_id = await ensure_embeddings(tenant_id, media_ids)
            try:
                classifier = registry.get_classifier()
            except Exception as exc:
                raise AIUnavailable(f"classifier unavailable: {exc!r}") from exc
        except AIUnavailable as exc:
            logger.warning("classification failed", extra=log_fields(error=str(exc)))
            await _fail(db, classification_id, AI_UNAVAILABLE)
            await db.commit()
            return ClassificationStatus.FAILED

        vectors = [
            _parse_vector(v)
            for v in await db.scalars(
                text(
                    "SELECT embedding::text FROM media_embeddings "
                    "WHERE model_id = :model AND media_id = ANY(:ids) ORDER BY media_id"
                ),
                {"model": model_id, "ids": media_ids},
            )
        ]
        prompts = {
            c.code: category_prompts(c.code, c.name_i18n.get("en", c.code), c.ai_prompts)
            for c in await db.scalars(select(Category).where(Category.is_active.is_(True)))
        }
        prompts[NOT_CIVIC] = default_prompts().get(NOT_CIVIC, [])
        await db.commit()
        if not vectors:
            await _fail(db, classification_id, AI_UNAVAILABLE)
            await db.commit()
            return ClassificationStatus.FAILED
        try:
            scores = await asyncio.to_thread(
                classifier.classify, np.array(vectors, dtype=np.float32), prompts
            )
        except Exception as exc:
            logger.warning("classifier failed", extra=log_fields(error=repr(exc)))
            await _fail(db, classification_id, AI_UNAVAILABLE)
            await db.commit()
            return ClassificationStatus.FAILED

        ranked = sorted(scores, key=lambda s: -s.confidence)
        top = ranked[0] if ranked else None
        await db.execute(
            update(Classification)
            .where(
                Classification.id == classification_id,
                Classification.status == ClassificationStatus.PENDING,
            )
            .values(
                status=ClassificationStatus.DONE,
                model_id=model_id,
                scores=[
                    {"code": s.code, "confidence": round(float(s.confidence), 4)} for s in ranked
                ],
                top_code=top.code if top else None,
                top_confidence=round(float(top.confidence), 4) if top else None,
                completed_at=datetime.now(UTC),
            )
        )
        await db.commit()
    return ClassificationStatus.DONE
