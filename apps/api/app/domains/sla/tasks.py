"""Celery task for the SLA scanner."""

from __future__ import annotations

import app.models  # noqa: F401  (every mapper configured in the worker process)
from app.domains.sla import service
from app.worker import celery_app, run_async


@celery_app.task(name="civicpulse.sla.scan")
def scan() -> int:
    """Mark issues past their SLA and escalate them (supervisors, then admins)."""
    return run_async(service.scan())
