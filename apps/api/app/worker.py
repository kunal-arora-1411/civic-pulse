"""Celery application for background jobs.

Jobs that touch the database should open
`app.core.tenancy.system_session(reason=...)` or set the tenant explicitly;
workers connect as the same non-superuser role as the API, so RLS applies to
them too. Tasks are thin sync wrappers that hand async code to `run_async`.

    celery -A app.worker:celery_app worker --loglevel=INFO
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()

celery_app = Celery(
    "civicpulse",
    broker=settings.broker_url,
    backend=settings.broker_url,
    include=["app.domains.media.tasks", "app.domains.housekeeping.tasks"],
)
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
    # Run by the `beat` service in compose. Hourly keeps the short-lived
    # tables small; the job is idempotent, so a missed or doubled run is fine.
    beat_schedule={
        "housekeeping-cleanup": {
            "task": "civicpulse.housekeeping.cleanup",
            "schedule": crontab(minute=17),
        },
    },
)


@setup_logging.connect
def _configure_logging(**_: Any) -> None:
    configure_logging(settings.log_level, "civicpulse-worker")


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion from a (sync) Celery task.

    Each call gets a fresh event loop, and asyncpg connections belong to the
    loop that opened them, so the engine's pool is disposed before the loop
    closes. The next task opens new connections on its own loop.
    """
    from app.core.db import get_engine

    async def runner() -> T:
        try:
            return await coro
        finally:
            await get_engine().dispose()

    return asyncio.run(runner())


@celery_app.task(name="civicpulse.ping")
def ping() -> str:
    """Round-trip check for the broker, the worker and the result backend."""
    return "pong"
