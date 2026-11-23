"""Celery application for background jobs.

Phase 0 only wires the plumbing (Redis broker, JSON serialisation, JSON logs)
and a `ping` task. Jobs that touch the database should open
`app.core.tenancy.system_session(reason=...)` or set the tenant explicitly;
workers connect as the same non-superuser role as the API, so RLS applies to
them too.

    celery -A app.worker:celery_app worker --loglevel=INFO
"""

from __future__ import annotations

from typing import Any

from celery import Celery
from celery.signals import setup_logging

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()

celery_app = Celery("civicpulse", broker=settings.broker_url, backend=settings.broker_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Only acknowledge once a task finishes, so a crashed worker's task is
    # redelivered. Tasks must therefore be idempotent.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
)


@setup_logging.connect
def _configure_logging(**_: Any) -> None:
    configure_logging(settings.log_level, "civicpulse-worker")


@celery_app.task(name="civicpulse.ping")
def ping() -> str:
    """Round-trip check for the broker, the worker and the result backend."""
    return "pong"
