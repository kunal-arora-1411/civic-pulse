"""Direct-to-storage uploads: issue a signed PUT, then verify what arrived."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFound
from app.core.logging import log_fields
from app.core.storage import ObjectStorage, ObjectTooLarge, StorageError
from app.domains.media.errors import (
    FileTooLarge,
    TooManyUploads,
    UnsupportedMediaType,
    UploadVerificationFailed,
)
from app.domains.media.inspect import EXTENSIONS, InvalidImage, inspect
from app.domains.media.models import ALLOWED_CONTENT_TYPES, MediaAsset, MediaStatus
from app.domains.media.schemas import (
    MediaAssetOut,
    MediaOut,
    MediaVariants,
    UploadCreate,
    UploadCreated,
)
from app.domains.rbac.principal import Principal

logger = logging.getLogger(__name__)


def object_key(tenant_id: uuid.UUID, asset_id: uuid.UUID, name: str) -> str:
    # Keys carry no user data, only opaque IDs.
    return f"{tenant_id}/media/{asset_id}/{name}"


async def create_upload(
    db: AsyncSession, storage: ObjectStorage, principal: Principal, body: UploadCreate
) -> UploadCreated:
    settings = get_settings()
    assert principal.tenant_id is not None
    if body.content_type not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedMediaType(details={"allowed": list(ALLOWED_CONTENT_TYPES)})
    if body.size_bytes > settings.media_max_bytes:
        raise FileTooLarge(details={"max_size_bytes": settings.media_max_bytes})

    # Serialise this user's upload creation so two parallel requests can't
    # both squeeze under the limit. The lock ends with the transaction.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"media-uploads:{principal.user_id}"},
    )
    now = datetime.now(UTC)
    pending = await db.scalar(
        select(func.count())
        .select_from(MediaAsset)
        .where(
            MediaAsset.owner_id == principal.user_id,
            MediaAsset.status == MediaStatus.PENDING,
            # An expired URL can't be used any more, so it doesn't hold a slot.
            MediaAsset.upload_expires_at > now,
        )
    )
    if (pending or 0) >= settings.media_max_pending_uploads:
        raise TooManyUploads(details={"limit": settings.media_max_pending_uploads})

    asset_id = uuid.uuid4()
    ttl = settings.media_upload_url_ttl_seconds
    key = object_key(principal.tenant_id, asset_id, f"original.{EXTENSIONS[body.content_type]}")
    db.add(
        MediaAsset(
            id=asset_id,
            tenant_id=principal.tenant_id,
            owner_id=principal.user_id,
            purpose=body.purpose,
            status=MediaStatus.PENDING,
            content_type=body.content_type,
            declared_size_bytes=body.size_bytes,
            checksum_sha256=body.checksum_sha256,
            storage_key=key,
            upload_expires_at=now + timedelta(seconds=ttl),
        )
    )
    await db.flush()
    url = storage.presign_put(
        key, content_type=body.content_type, content_length=body.size_bytes, expires_in=ttl
    )
    return UploadCreated(
        upload_id=asset_id,
        url=url,
        headers={"Content-Type": body.content_type},
        expires_in=ttl,
        max_size_bytes=settings.media_max_bytes,
    )


async def _verify(storage: ObjectStorage, asset: MediaAsset) -> tuple[int, int, int, dict]:
    """Check the stored object against the declaration. Returns
    (size, width, height, exif) or raises InvalidImage with a reason."""
    settings = get_settings()
    head = await storage.head(asset.storage_key)
    if head is None:
        raise InvalidImage("object_missing")
    if head.size != asset.declared_size_bytes:
        raise InvalidImage("size_mismatch")
    try:
        data = await storage.read(asset.storage_key, max_bytes=settings.media_max_bytes)
    except ObjectTooLarge:
        raise InvalidImage("size_mismatch") from None
    if hashlib.sha256(data).hexdigest() != asset.checksum_sha256:
        raise InvalidImage("checksum_mismatch")
    info = await asyncio.to_thread(
        inspect,
        data,
        declared_type=asset.content_type,
        max_pixels=settings.media_max_pixels,
        tz=settings.local_timezone,
    )
    exif = dict(info.exif.private)
    return len(data), info.width, info.height, exif


async def complete_upload(
    db: AsyncSession, storage: ObjectStorage, principal: Principal, upload_id: uuid.UUID
) -> MediaAsset:
    """Verify an uploaded object and mark the asset `processing`.

    Completing twice is harmless: an already verified asset is returned as
    it is. A failed verification deletes the object and marks the asset
    `failed`, and that write is committed even though the response is an
    error, so the upload can't be completed again.
    """
    asset = await db.scalar(
        select(MediaAsset)
        .where(MediaAsset.id == upload_id, MediaAsset.owner_id == principal.user_id)
        .with_for_update()
    )
    if asset is None:
        raise NotFound()
    if asset.status == MediaStatus.FAILED:
        raise UploadVerificationFailed(details={"reason": asset.failure_reason})
    if asset.status != MediaStatus.PENDING:
        return asset

    try:
        size, width, height, exif = await _verify(storage, asset)
    except InvalidImage as exc:
        await _fail(db, storage, asset, exc.reason)
        raise UploadVerificationFailed(details={"reason": exc.reason}) from None

    asset.status = MediaStatus.PROCESSING
    asset.size_bytes = size
    asset.width = width
    asset.height = height
    asset.exif = exif or None
    captured = exif.get("captured_at")
    # Stored and returned in UTC like every other timestamp; the offset the
    # photo was taken at is kept in the private EXIF copy.
    asset.captured_at = datetime.fromisoformat(captured).astimezone(UTC) if captured else None
    asset.verified_at = datetime.now(UTC)
    await db.flush()
    return asset


async def _fail(db: AsyncSession, storage: ObjectStorage, asset: MediaAsset, reason: str) -> None:
    try:
        await storage.delete([asset.storage_key])
    except StorageError as exc:
        # The housekeeping job deletes objects of failed uploads later.
        logger.warning(
            "could not delete rejected upload",
            extra=log_fields(media_id=str(asset.id), error=str(exc)),
        )
    asset.status = MediaStatus.FAILED
    asset.failure_reason = reason
    # Deliberate commit inside a service: the request ends in an error
    # response, which would otherwise roll this state change back.
    await db.commit()
    logger.info("upload rejected", extra=log_fields(media_id=str(asset.id), reason=reason))


def _sign(storage: ObjectStorage, key: str | None) -> str | None:
    if key is None:
        return None
    return storage.presign_get(key, expires_in=get_settings().media_download_url_ttl_seconds)


def to_asset_out(storage: ObjectStorage, asset: MediaAsset) -> MediaAssetOut:
    ready = asset.status == MediaStatus.READY
    return MediaAssetOut(
        id=asset.id,
        status=MediaStatus(asset.status),
        content_type=asset.content_type,
        width=asset.width,
        height=asset.height,
        variants=MediaVariants(
            thumb=_sign(storage, asset.thumb_key) if ready else None,
            display=_sign(storage, asset.display_key) if ready else None,
        ),
        captured_at=asset.captured_at,
    )


def to_media_out(storage: ObjectStorage, asset: MediaAsset, *, staff: bool) -> MediaOut:
    """The embedded media shape. Only staff get the original, which still
    carries its metadata (GPS included); everyone else sees the stripped
    variants, and only once they exist."""
    ready = asset.status == MediaStatus.READY
    return MediaOut(
        id=asset.id,
        status=MediaStatus(asset.status),
        width=asset.width,
        height=asset.height,
        thumb_url=_sign(storage, asset.thumb_key) if ready else None,
        display_url=_sign(storage, asset.display_key) if ready else None,
        original_url=_sign(storage, asset.storage_key) if staff else None,
        captured_at=asset.captured_at,
    )


def thumb_url(storage: ObjectStorage, status: str | None, key: str | None) -> str | None:
    return _sign(storage, key) if status == MediaStatus.READY else None
