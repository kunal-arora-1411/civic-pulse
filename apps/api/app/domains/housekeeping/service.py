"""Periodic cleanup of short-lived rows and abandoned uploads.

Runs across every tenant, so it uses the RLS bypass (a system job, as ADR
0002 allows). Each step is its own transaction: a failure in one doesn't
undo the others, and the next run picks up whatever was left.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import Delete, delete, or_, select, update

from app.core.config import get_settings
from app.core.idempotency import IdempotencyKey
from app.core.logging import log_fields
from app.core.storage import ObjectStorage, StorageError, get_storage
from app.core.tenancy import system_session
from app.domains.auth.models import AuthSession, OtpChallenge
from app.domains.media.models import MediaAsset, MediaStatus
from app.domains.outbox.service import purge_dispatched

logger = logging.getLogger(__name__)

# An OTP challenge also carries the MFA step that follows it, so it is kept
# a little past its own expiry rather than deleted the moment it lapses.
OTP_GRACE = timedelta(hours=1)
SESSION_RETENTION = timedelta(days=30)
UPLOAD_RETENTION = timedelta(hours=24)
# A verified upload should be processed within seconds; this long means the
# queue message was lost (broker down when it was sent, for example).
STUCK_PROCESSING = timedelta(minutes=15)
_UPLOAD_BATCH = 500


@dataclass
class CleanupResult:
    otp_challenges: int = 0
    auth_sessions: int = 0
    idempotency_keys: int = 0
    uploads: int = 0
    outbox: int = 0
    purged_originals: int = 0
    stuck_processing: list[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {
            "otp_challenges": self.otp_challenges,
            "auth_sessions": self.auth_sessions,
            "idempotency_keys": self.idempotency_keys,
            "uploads": self.uploads,
            "outbox": self.outbox,
            "purged_originals": self.purged_originals,
            "stuck_processing": len(self.stuck_processing),
        }


async def _delete_rows(statement: Delete, reason: str) -> int:
    async with system_session(reason=reason) as db:
        result = await db.execute(statement)
        return int(result.rowcount or 0)  # pyright: ignore[reportAttributeAccessIssue]


async def _delete_abandoned_uploads(storage: ObjectStorage, cutoff: datetime) -> int:
    """Unattached uploads that never completed (or failed), with their objects.

    Objects go first. If storage refuses, the rows stay so the next run
    tries again; deleting rows first would orphan the objects for good.
    """
    removed = 0
    while True:
        async with system_session(reason="housekeeping: abandoned uploads") as db:
            rows = (
                await db.execute(
                    select(
                        MediaAsset.id,
                        MediaAsset.storage_key,
                        MediaAsset.display_key,
                        MediaAsset.thumb_key,
                    )
                    .where(
                        MediaAsset.status.in_([MediaStatus.PENDING, MediaStatus.FAILED]),
                        MediaAsset.report_id.is_(None),
                        MediaAsset.created_at < cutoff,
                    )
                    .order_by(MediaAsset.created_at)
                    .limit(_UPLOAD_BATCH)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            if not rows:
                return removed
            keys = [key for row in rows for key in row[1:] if key]
            try:
                await storage.delete(keys)
            except StorageError as exc:
                logger.warning(
                    "housekeeping: could not delete upload objects",
                    extra=log_fields(error=str(exc)),
                )
                return removed
            await db.execute(delete(MediaAsset).where(MediaAsset.id.in_([row[0] for row in rows])))
            removed += len(rows)
        if len(rows) < _UPLOAD_BATCH:
            return removed


async def _purge_original_media(storage: ObjectStorage, cutoff: datetime) -> int:
    """Delete original photos processed before `cutoff` (P6-12).

    Only ready photos whose public variants exist, and that passed the face
    check when blurring is on, so nothing still needs the original. Objects
    go first, as above; the row keeps its key and records the purge.
    """
    settings = get_settings()
    removed = 0
    while True:
        async with system_session(reason="housekeeping: media retention") as db:
            query = (
                select(MediaAsset.id, MediaAsset.storage_key)
                .where(
                    MediaAsset.status == MediaStatus.READY,
                    MediaAsset.original_purged_at.is_(None),
                    MediaAsset.processed_at < cutoff,
                    MediaAsset.display_key.is_not(None),
                )
                .order_by(MediaAsset.processed_at)
                .limit(_UPLOAD_BATCH)
                .with_for_update(skip_locked=True)
            )
            if settings.face_blur_enabled:
                query = query.where(MediaAsset.faces_checked_at.is_not(None))
            rows = (await db.execute(query)).all()
            if not rows:
                return removed
            try:
                await storage.delete([row[1] for row in rows])
            except StorageError as exc:
                logger.warning(
                    "housekeeping: could not delete original media",
                    extra=log_fields(error=str(exc)),
                )
                return removed
            await db.execute(
                update(MediaAsset)
                .where(MediaAsset.id.in_([row[0] for row in rows]))
                .values(original_purged_at=datetime.now(UTC), exif=None)
            )
            removed += len(rows)
        if len(rows) < _UPLOAD_BATCH:
            return removed


async def cleanup(
    storage: ObjectStorage | None = None, *, now: datetime | None = None
) -> CleanupResult:
    now = now or datetime.now(UTC)
    storage = storage or get_storage()
    result = CleanupResult()

    result.otp_challenges = await _delete_rows(
        delete(OtpChallenge).where(OtpChallenge.expires_at < now - OTP_GRACE),
        "housekeeping: expired OTP challenges",
    )
    result.auth_sessions = await _delete_rows(
        delete(AuthSession).where(
            or_(
                AuthSession.expires_at < now - SESSION_RETENTION,
                AuthSession.revoked_at < now - SESSION_RETENTION,
            )
        ),
        "housekeeping: old sessions",
    )
    result.idempotency_keys = await _delete_rows(
        delete(IdempotencyKey).where(IdempotencyKey.expires_at < now),
        "housekeeping: expired idempotency keys",
    )
    result.uploads = await _delete_abandoned_uploads(storage, now - UPLOAD_RETENTION)
    # Dispatched outbox events past retention, with their delivery rows.
    result.outbox = await purge_dispatched(
        older_than_days=get_settings().outbox_retention_days, now=now
    )

    retention_days = get_settings().media_original_retention_days
    if retention_days > 0:
        result.purged_originals = await _purge_original_media(
            storage, now - timedelta(days=retention_days)
        )

    async with system_session(reason="housekeeping: stuck media") as db:
        result.stuck_processing = [
            (row[0], row[1])
            for row in await db.execute(
                select(MediaAsset.id, MediaAsset.tenant_id).where(
                    MediaAsset.status == MediaStatus.PROCESSING,
                    MediaAsset.verified_at < now - STUCK_PROCESSING,
                )
            )
        ]

    logger.info("housekeeping finished", extra=log_fields(**result.summary()))
    return result
