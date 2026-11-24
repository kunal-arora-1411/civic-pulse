"""Celery tasks on the `ai` queue: photo analysis and classification.

Both are idempotent, so retries and redelivery (acks_late) are harmless.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from celery.signals import worker_ready

import app.models  # noqa: F401  (every mapper configured in the worker process)
from app.core.storage import StorageError
from app.domains.ai import analysis, classifications
from app.jobs import ANALYZE_MEDIA, CLASSIFY
from app.worker import AI_QUEUE, celery_app, run_async

logger = logging.getLogger(__name__)


def consumes_ai_queue(consumer: Any) -> bool:
    queues = getattr(consumer.app.amqp.queues, "consume_from", None) or {}
    return AI_QUEUE in queues


@worker_ready.connect
def register_models(sender: Any = None, **_: Any) -> None:
    """The worker that consumes the `ai` queue records its models in
    model_registry when it starts. The regular worker never loads a model,
    so it leaves the registry alone. A failure is logged, not fatal: the
    first embedding still registers a minimal row."""
    if sender is None or not consumes_ai_queue(sender):
        return
    try:
        run_async(analysis.register_models())
    except Exception:
        logger.exception("could not register the deployed models")


@celery_app.task(
    name=ANALYZE_MEDIA,
    autoretry_for=(StorageError, analysis.AIUnavailable),
    retry_backoff=True,
    retry_backoff_max=120,
    max_retries=5,
)
def analyze_media(media_id: str, tenant_id: str) -> str:
    return run_async(analysis.analyze_media(uuid.UUID(media_id), uuid.UUID(tenant_id)))


@celery_app.task(
    name=CLASSIFY,
    autoretry_for=(StorageError,),
    retry_backoff=True,
    retry_backoff_max=10,
    max_retries=3,
)
def classify(classification_id: str, tenant_id: str) -> str:
    """A citizen is waiting on this one, so retries are short; whatever is
    still pending after the timeout is failed and the citizen picks."""
    return run_async(classifications.run(uuid.UUID(classification_id), uuid.UUID(tenant_id)))
