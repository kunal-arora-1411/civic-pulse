"""Background work the API asks for, behind one injectable dependency.

Requests hand work to Celery by task name, so the API never imports the
task modules (which import the worker app and every mapper). Tests swap
`get_jobs` for an implementation that runs the work inline or records it,
so nothing in the suite reaches the broker.

Enqueue from `BackgroundTasks` where possible: those run after the
request's transaction has committed, so the worker always finds the rows
it is told about. If the broker is down the call logs and returns; each
kind of work has a sweeper that picks up what was never queued (the
matching watchdog, the nightly priority run).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Annotated, Protocol

from fastapi import Depends

from app.core.logging import log_fields

logger = logging.getLogger(__name__)

RECOMPUTE_TENANT = "civicpulse.priority.recompute_tenant"
MATCH_REPORT = "civicpulse.matching.match_report"
CLASSIFY = "civicpulse.ai.classify"
ANALYZE_MEDIA = "civicpulse.ai.analyze_media"

# Give up on the broker quickly: a request must not hang on it.
_RETRY_POLICY = {"max_retries": 2, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.5}


class Jobs(Protocol):
    async def recompute_priorities(
        self, tenant_id: uuid.UUID, category_id: uuid.UUID | None = None
    ) -> None: ...

    async def match_report(self, report_id: uuid.UUID, tenant_id: uuid.UUID) -> None: ...

    async def classify(self, classification_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
        """Queue a classification; False if it couldn't be queued at all."""
        ...


class CeleryJobs:
    async def _send(self, name: str, *args: str) -> bool:
        from app.worker import celery_app

        try:
            # A broker round trip; keep it off the event loop.
            await asyncio.to_thread(
                celery_app.send_task, name, args=list(args), retry_policy=_RETRY_POLICY
            )
        except Exception as exc:  # broker down: the sweepers catch up later
            logger.error("could not queue a job", extra=log_fields(task=name, error=repr(exc)))
            return False
        return True

    async def recompute_priorities(
        self, tenant_id: uuid.UUID, category_id: uuid.UUID | None = None
    ) -> None:
        extra = [str(category_id)] if category_id else []
        await self._send(RECOMPUTE_TENANT, str(tenant_id), *extra)

    async def match_report(self, report_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        await self._send(MATCH_REPORT, str(report_id), str(tenant_id))

    async def classify(self, classification_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
        return await self._send(CLASSIFY, str(classification_id), str(tenant_id))


def get_jobs() -> Jobs:
    return CeleryJobs()


JobsDep = Annotated[Jobs, Depends(get_jobs)]
