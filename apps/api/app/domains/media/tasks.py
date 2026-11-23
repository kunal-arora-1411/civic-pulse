"""Celery tasks for media, and the queue the API uses to reach them."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Protocol

from fastapi import Depends

import app.models  # noqa: F401  (every mapper configured in the worker process)
from app.core.logging import log_fields
from app.core.storage import StorageError
from app.domains.media.processing import process_asset
from app.worker import celery_app, run_async

logger = logging.getLogger(__name__)


@celery_app.task(
    name="civicpulse.media.process",
    autoretry_for=(StorageError,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=6,
)
def process_media(asset_id: str, tenant_id: str) -> str:
    return run_async(process_asset(uuid.UUID(asset_id), uuid.UUID(tenant_id)))


class MediaQueue(Protocol):
    def enqueue(self, asset_id: uuid.UUID, tenant_id: uuid.UUID) -> None: ...


class CeleryMediaQueue:
    def enqueue(self, asset_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        try:
            process_media.delay(str(asset_id), str(tenant_id))
        except Exception as exc:  # broker down: housekeeping re-queues stuck assets
            logger.error(
                "could not queue media processing",
                extra=log_fields(media_id=str(asset_id), error=repr(exc)),
            )


def get_media_queue() -> MediaQueue:
    return CeleryMediaQueue()


MediaQueueDep = Annotated[MediaQueue, Depends(get_media_queue)]
