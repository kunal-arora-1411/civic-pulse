from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, status

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.storage import Storage
from app.domains.media import service
from app.domains.media.models import MediaStatus
from app.domains.media.schemas import MediaAssetOut, UploadCreate, UploadCreated
from app.domains.media.tasks import MediaQueueDep
from app.domains.rbac.dependencies import require_any
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal

router = APIRouter(prefix="/media", tags=["media"])

Uploader = Annotated[Principal, require_any(Permission.REPORT_CREATE, Permission.EVIDENCE_UPLOAD)]


@router.post(
    "/uploads",
    operation_id="media_create_upload",
    response_model=UploadCreated,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 422, 429),
)
async def create_upload(
    principal: Uploader, db: DbSession, storage: Storage, body: UploadCreate
) -> UploadCreated:
    """Step 1: get a pre-signed URL. The client then PUTs the bytes to it."""
    return await service.create_upload(db, storage, principal, body)


@router.post(
    "/uploads/{upload_id}/complete",
    operation_id="media_complete_upload",
    response_model=MediaAssetOut,
    responses=error_responses(401, 403, 404, 422, 503),
)
async def complete_upload(
    principal: Uploader,
    db: DbSession,
    storage: Storage,
    queue: MediaQueueDep,
    background: BackgroundTasks,
    upload_id: uuid.UUID,
) -> MediaAssetOut:
    """Step 3: verify the uploaded bytes (size, checksum, real image type),
    and scan them for malware when a scanner is configured.

    On failure the object is deleted and the upload can't be retried; start
    a new one. On success the asset is `processing` until the worker has
    made its variants.
    """
    asset = await service.complete_upload(db, storage, principal, upload_id)
    if asset.status == MediaStatus.PROCESSING:
        # Background tasks run after the response, and the request's
        # transaction commits before the response is sent, so the worker
        # always finds the verified row. Re-queuing on a repeated completion
        # is harmless: processing is idempotent.
        background.add_task(queue.enqueue, asset.id, asset.tenant_id)
    return service.to_asset_out(storage, asset)
