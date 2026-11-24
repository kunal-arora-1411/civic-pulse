from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.core.db import DbSession
from app.core.errors import ValidationFailed, error_responses
from app.domains.ai import classifications, governance
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


admin_router = APIRouter(prefix="/admin/ai", tags=["admin"])
ConfigReader = Annotated[Principal, require(Permission.CONFIG_READ)]


@admin_router.get(
    "/models",
    operation_id="admin_list_ai_models",
    response_model=governance.ModelList,
    responses=error_responses(401, 403),
)
async def list_ai_models(_: ConfigReader, db: DbSession) -> governance.ModelList:
    """Deployed models with their source, licence and evaluation metrics;
    `active` marks the most recently deployed model per task."""
    return await governance.list_models(db)


@admin_router.get(
    "/quality",
    operation_id="admin_get_ai_quality",
    response_model=governance.QualityOut,
    responses=error_responses(401, 403, 422),
)
async def get_ai_quality(
    _: ConfigReader,
    db: DbSession,
    date_from: Annotated[
        date | None,
        Query(alias="from", description="First day (Asia/Kolkata). Default: 29 days before `to`."),
    ] = None,
    date_to: Annotated[
        date | None, Query(alias="to", description="Last day. Default: today.")
    ] = None,
) -> governance.QualityOut:
    """Counts for a window of whole days: classifications done and failed,
    suggestions accepted and corrected by category, how reports were
    matched, review outcomes, and feedback on automatic links."""
    default_from, default_to = governance.default_window(date_to)
    start, end = date_from or default_from, date_to or default_to
    if start > end:
        raise ValidationFailed(
            "The request is invalid.",
            details={
                "errors": [
                    {
                        "loc": ["query", "from"],
                        "msg": "`from` is after `to`.",
                        "type": "value_error",
                    }
                ]
            },
        )
    return await governance.quality(db, start, end)
