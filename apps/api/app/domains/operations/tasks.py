"""Celery task for the resolution window."""

from __future__ import annotations

import app.models  # noqa: F401  (every mapper configured in the worker process)
from app.domains.operations import closure
from app.worker import celery_app, run_async


@celery_app.task(name="civicpulse.operations.close_resolved")
def close_resolved() -> int:
    """`resolved` → `closed` once the tenant's resolution window has passed."""
    return run_async(closure.close_expired())
