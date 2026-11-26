"""Celery tasks for the outbox dispatcher."""

from __future__ import annotations

import uuid

import app.models  # noqa: F401  (every mapper configured in the worker process)
from app.domains.outbox import service
from app.worker import celery_app, run_async


@celery_app.task(name="civicpulse.outbox.dispatch")
def dispatch_events() -> dict[str, int]:
    """Deliver undispatched domain events on every configured channel."""
    return run_async(service.dispatch()).as_dict()


@celery_app.task(name="civicpulse.outbox.deliver_event")
def deliver_event(event_id: str) -> dict[str, int]:
    """Deliver one event straight away (a sign-in code), if still due."""
    return run_async(service.dispatch_event(uuid.UUID(event_id))).as_dict()
