"""Celery tasks that recompute priorities in bulk."""

from __future__ import annotations

import uuid

import app.models  # noqa: F401  (every mapper configured in the worker process)
from app.domains.priority import service
from app.jobs import RECOMPUTE_TENANT
from app.worker import celery_app, run_async


@celery_app.task(name=RECOMPUTE_TENANT)
def recompute_tenant(tenant_id: str, category_id: str | None = None) -> int:
    """After a priority config or severity rule change."""
    category = uuid.UUID(category_id) if category_id else None
    return run_async(service.recompute_tenant(uuid.UUID(tenant_id), category_id=category))


@celery_app.task(name="civicpulse.priority.nightly")
def nightly() -> int:
    """Age changes every open issue's score; Beat runs this once a night."""
    return run_async(service.recompute_all())
