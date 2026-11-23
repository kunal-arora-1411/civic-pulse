from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Response, status
from fastapi.responses import JSONResponse

from app.core import idempotency
from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.storage import Storage
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.reports import service
from app.domains.reports.schemas import ReportCreate, ReportOwnerView

router = APIRouter(tags=["reports"])

RequiredIdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
        pattern=r"^[\x21-\x7e]+$",
        description="Required. One key per submission attempt: a retry with the same key and "
        "body returns the original report instead of creating another.",
    ),
]


@router.post(
    "/reports",
    operation_id="reports_create",
    response_model=ReportOwnerView,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 422),
)
async def create_report(
    principal: Annotated[Principal, require(Permission.REPORT_CREATE)],
    db: DbSession,
    storage: Storage,
    body: ReportCreate,
    idempotency_key: RequiredIdempotencyKey,
) -> Any:
    """Submit a report. Creates its civic issue in the same transaction."""
    claim = await idempotency.begin(
        db,
        key=idempotency_key,
        scope="POST /reports",
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        body=body,
    )
    if isinstance(claim, Response):
        return await _replay(db, storage, claim)

    report_id = await service.create_report(db, principal, body)
    view = await service.get_owner_view(db, storage, report_id)
    assert view is not None
    await idempotency.complete(db, claim, status.HTTP_201_CREATED, view)
    return view


async def _replay(db: DbSession, storage: Storage, stored: Response) -> Response:
    """Replay a submission, but with fresh content.

    The stored body holds signed media URLs that expire after minutes, and a
    status that may have moved on, so the replay re-renders the same report
    and keeps the original status code and the replay header.
    """
    body = json.loads(bytes(stored.body))
    view = await service.get_owner_view(db, storage, uuid.UUID(body["id"]))
    if view is None:  # pragma: no cover - reports are never deleted
        return stored
    return JSONResponse(
        view.model_dump(mode="json"),
        status_code=stored.status_code,
        headers={idempotency.REPLAY_HEADER: "true"},
    )
