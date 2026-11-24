"""Celery tasks for duplicate matching."""

from __future__ import annotations

import uuid

from celery import Task

import app.models  # noqa: F401  (every mapper configured in the worker process)
from app.core.storage import StorageError
from app.domains.matching import service
from app.jobs import MATCH_REPORT
from app.worker import celery_app, run_async


@celery_app.task(
    name=MATCH_REPORT,
    bind=True,
    autoretry_for=(StorageError,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=20,
)
def match_report(self: Task, report_id: str, tenant_id: str) -> str:
    """Runs on the `ai` queue. While the photos have no embeddings it
    retries every few seconds; past the fallback deadline it matches
    without them. A no-op for a report that is no longer pending."""
    outcome = run_async(service.process_report(uuid.UUID(report_id), uuid.UUID(tenant_id)))
    if outcome.retry_in is not None:
        raise self.retry(countdown=outcome.retry_in)
    return outcome.status


@celery_app.task(name="civicpulse.matching.watchdog")
def watchdog() -> dict[str, int]:
    result = run_async(service.watchdog())
    for report_id, tenant_id in result.requeue:
        match_report.delay(str(report_id), str(tenant_id))
    return result.summary()
