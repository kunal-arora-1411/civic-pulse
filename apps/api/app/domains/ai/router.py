from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Response, status

from app.core.db import DbSession
from app.core.errors import error_responses
from app.domains.ai import classifications
from app.domains.ai.models import ClassificationStatus
from app.domains.ai.schemas import ClassificationCreate, ClassificationOut
from app.domains.auth.dependencies import CurrentPrincipal
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.jobs import JobsDep

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post(
    "/classifications",
    operation_id="ai_create_classification",
    response_model=ClassificationOut,
    responses={
        202: {"model": ClassificationOut, "description": "Still running: poll GET."},
        **error_responses(401, 403, 422),
    },
)
async def create_classification(
    principal: Annotated[Principal, require(Permission.REPORT_CREATE)],
    db: DbSession,
    jobs: JobsDep,
    body: ClassificationCreate,
    response: Response,
) -> ClassificationOut:
    """Suggest categories for the caller's uploaded photos (completed
    uploads only). Waits up to 4 s: `200` with the result if it is ready
    (`done`, or `failed` with `error: "ai_unavailable"`), otherwise `202`
    with `status: "pending"`; poll GET every 1-2 s, for about 15 s."""
    classification_id = await classifications.request(db, jobs, principal, body)
    classification = await classifications.get_own(db, principal, classification_id)
    if classification.status == ClassificationStatus.PENDING:
        response.status_code = status.HTTP_202_ACCEPTED
    return await classifications.to_out(db, classification)


@router.get(
    "/classifications/{classification_id}",
    operation_id="ai_get_classification",
    response_model=ClassificationOut,
    responses=error_responses(401, 404, 422),
)
async def get_classification(
    principal: CurrentPrincipal, db: DbSession, classification_id: uuid.UUID
) -> ClassificationOut:
    """The caller's own classification; anyone else's is 404."""
    classification = await classifications.get_own(db, principal, classification_id)
    return await classifications.to_out(db, classification)
