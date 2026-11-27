"""Celery tasks for the audit chain (scheduled by Celery Beat, see app/worker.py).

Both tasks are thin wrappers: the work lives in `checkpoints.py` (sealing) and
`runs.py` (verification). Neither raises on a broken chain -- a failed task would
be redelivered by `acks_late` and re-do the same scan -- so a break is a recorded
row plus an ERROR log line, which is what alerting watches.
"""

from __future__ import annotations

import uuid

import app.models  # noqa: F401  (every mapper configured in the worker process)
from app.domains.audit import checkpoints, runs
from app.worker import celery_app, run_async


@celery_app.task(name="civicpulse.audit.checkpoint")
def run_checkpoint() -> dict[str, int]:
    """Seal every chain whose head has moved since its last checkpoint. Hourly."""
    return run_async(checkpoints.seal_all_chains())


@celery_app.task(name="civicpulse.audit.verify")
def run_verify(verification_id: str | None = None) -> dict[str, int]:
    """Run one requested verification, or the nightly sweep over every chain."""
    if verification_id is not None:
        return run_async(runs.execute(uuid.UUID(verification_id)))
    return run_async(runs.sweep())
