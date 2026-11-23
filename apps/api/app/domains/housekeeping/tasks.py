"""The periodic cleanup task (scheduled by Celery Beat, see app/worker.py)."""

from __future__ import annotations

import app.models  # noqa: F401  (every mapper configured in the worker process)
from app.domains.housekeeping.service import cleanup
from app.domains.media.tasks import process_media
from app.worker import celery_app, run_async


@celery_app.task(name="civicpulse.housekeeping.cleanup")
def run_cleanup() -> dict[str, int]:
    result = run_async(cleanup())
    for asset_id, tenant_id in result.stuck_processing:
        process_media.delay(str(asset_id), str(tenant_id))
    return result.summary()
