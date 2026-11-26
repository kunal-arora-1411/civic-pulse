"""Per-photo AI work: embeddings and perceptual hashes, and face blurring.

Both read the original upload (never altered) and are safe to repeat:
an embedding is stored once per photo and model (a duplicate insert is a
no-op), and the face check is recorded on the asset so it happens once.
With face blurring on, the face check is also what publishes a photo's
public copies (`check_faces`).

Model failures surface as `AIUnavailable`; storage failures as
`StorageError`, which callers retry. Vectors go to Postgres as text cast
to `vector`, so no driver-level codec is needed.
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import numpy as np
from PIL import Image
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import registry
from app.ai.faces import blur_regions
from app.ai.fake import FAKE_MODEL_ID
from app.ai.interfaces import VisionModel
from app.ai.metrics import metrics_for
from app.ai.phash import perceptual_hash, to_signed64
from app.core.config import get_settings
from app.core.db import get_session_factory
from app.core.logging import log_fields
from app.core.storage import ObjectStorage, get_storage
from app.core.tenancy import set_tenant
from app.domains.ai.models import EMBEDDING_DIM, MediaEmbedding, ModelRegistryEntry, ModelTask
from app.domains.media.inspect import InvalidImage
from app.domains.media.models import MediaAsset, MediaStatus
from app.domains.media.processing import Variant, decode_upright, render_image_variants
from app.domains.media.service import object_key

logger = logging.getLogger(__name__)


class AIUnavailable(Exception):
    """The vision model couldn't be loaded or failed to run."""


def vision_model() -> VisionModel:
    try:
        model = registry.get_vision_model()
    except Exception as exc:
        raise AIUnavailable(f"vision model unavailable: {exc!r}") from exc
    if model.dim != EMBEDDING_DIM:
        raise AIUnavailable(
            f"model {model.model_id} has {model.dim} dimensions, not {EMBEDDING_DIM}"
        )
    return model


_FAKE_ROW: dict[str, Any] = {
    "task": ModelTask.EMBEDDING,
    "name": "Fake vision model (deterministic)",
    "version": FAKE_MODEL_ID.rpartition("@")[2],
    "source": "apps/api/app/ai/fake.py",
    "license": "Project code; no third-party weights",
    "intended_use": "Tests and development only",
}


async def ensure_registered(db: AsyncSession, model: VisionModel) -> None:
    """Make sure the model has a registry row (embeddings reference it).

    The AI worker records full details at start-up (`register_models`);
    this only fills in a minimal row if that hasn't happened, and never
    touches an existing one.
    """
    model_id = model.model_id
    if model_id == FAKE_MODEL_ID:
        values = dict(_FAKE_ROW)
    else:
        values = {
            "task": ModelTask.EMBEDDING,
            "name": model_id,
            "version": model_id.rpartition("@")[2] or model_id,
            "metrics": metrics_for(model_id),
        }
    await db.execute(
        pg_insert(ModelRegistryEntry)
        .values(id=model_id, **values)
        .on_conflict_do_nothing(index_elements=[ModelRegistryEntry.id])
    )


async def register_models() -> list[str]:
    """Record the models this process runs, as deployed now.

    The AI worker calls this when it starts (PRD §8.6: source, licence and
    intended use of every deployed model are on record). Real models are
    described by the lock next to their weights, fakes by their module;
    both get the evaluation's metrics, including the per-model matching
    defaults. Re-registering refreshes the details and makes the model the
    active one for its task again. Returns the model ids.
    """
    if get_settings().ai_provider == "fake":
        rows = [{"model_id": FAKE_MODEL_ID, **_FAKE_ROW}]
    else:
        rows = [model.registry_row() for model in registry.deployed_models()]
    ids: list[str] = []
    async with get_session_factory()() as db:
        for row in rows:
            model_id = row.pop("model_id")
            ids.append(model_id)
            values = {**row, "metrics": metrics_for(model_id), "deployed_at": func.now()}
            await db.execute(
                pg_insert(ModelRegistryEntry)
                .values(id=model_id, **values)
                .on_conflict_do_update(index_elements=[ModelRegistryEntry.id], set_=values)
            )
        await db.commit()
    logger.info("models registered", extra=log_fields(models=",".join(ids)))
    return ids


def _vector_literal(vector: np.ndarray) -> str:
    return "[" + ",".join(f"{float(v):.7g}" for v in vector) + "]"


def _embed(model: VisionModel, originals: Sequence[bytes]) -> list[tuple[str, int]]:
    max_pixels = get_settings().media_max_pixels
    images: list[Image.Image] = []
    for data in originals:
        image = decode_upright(data, max_pixels=max_pixels)
        # The decoded copy loses the PNG text / JPEG comment the fake model
        # reads; reopen for that metadata but use the upright pixels.
        source = Image.open(io.BytesIO(data))
        image.info.update(source.info)
        images.append(image)
    vectors = model.embed_images(images)
    return [
        (_vector_literal(vector), to_signed64(perceptual_hash(image)))
        for vector, image in zip(vectors, images, strict=True)
    ]


_INSERT_EMBEDDING = text(
    "INSERT INTO media_embeddings (tenant_id, media_id, model_id, embedding, phash) "
    "VALUES (:tenant_id, :media_id, :model_id, CAST(:embedding AS vector), :phash) "
    "ON CONFLICT (media_id, model_id) DO NOTHING"
)


async def ensure_embeddings(
    tenant_id: uuid.UUID,
    media_ids: Sequence[uuid.UUID],
    *,
    storage: ObjectStorage | None = None,
) -> str:
    """Embed whichever of these photos have no embedding for the current
    model yet. Returns the model id. Raises AIUnavailable or StorageError."""
    model = vision_model()
    storage = storage or get_storage()
    max_bytes = get_settings().media_max_bytes
    async with get_session_factory()() as db:
        await set_tenant(db, tenant_id)
        await ensure_registered(db, model)
        done = set(
            await db.scalars(
                text(
                    "SELECT media_id FROM media_embeddings "
                    "WHERE model_id = :model AND media_id = ANY(:ids)"
                ),
                {"model": model.model_id, "ids": list(media_ids)},
            )
        )
        missing = (
            await db.execute(
                select(MediaAsset.id, MediaAsset.storage_key)
                .where(MediaAsset.id.in_([m for m in media_ids if m not in done]))
                .where(MediaAsset.status.in_([MediaStatus.PROCESSING, MediaStatus.READY]))
                .order_by(MediaAsset.id)
            )
        ).all()
        await db.commit()  # don't hold a transaction while reading and embedding
        if not missing:
            return model.model_id

        originals = [await storage.read(key, max_bytes=max_bytes) for _, key in missing]
        try:
            rows = await asyncio.to_thread(_embed, model, originals)
        except InvalidImage as exc:  # verified at upload, so this is unexpected
            logger.error("could not decode a photo for embedding", extra=log_fields(error=str(exc)))
            raise AIUnavailable(f"undecodable photo: {exc.reason}") from exc
        except Exception as exc:
            raise AIUnavailable(f"embedding failed: {exc!r}") from exc
        for (media_id, _), (embedding, phash) in zip(missing, rows, strict=True):
            await db.execute(
                _INSERT_EMBEDDING,
                {
                    "tenant_id": tenant_id,
                    "media_id": media_id,
                    "model_id": model.model_id,
                    "embedding": embedding,
                    "phash": phash,
                },
            )
        await db.commit()
    logger.info("photos embedded", extra=log_fields(model_id=model.model_id, count=len(missing)))
    return model.model_id


async def refresh_phashes(tenant_id: uuid.UUID, *, storage: ObjectStorage | None = None) -> int:
    """Re-hash stored embeddings whose pHash isn't the photo's current one.

    Rows written while a difference hash stood in for the real pHash hold
    another kind of hash, which never comes within the same-photo distance
    of a real one, so a re-upload of those photos would go unnoticed. The
    seed runs this; it reads each original once and is safe to repeat.
    Embedding rows are insert-only for the app role, so a stale row is
    replaced (same vector, new hash) rather than updated. Returns the
    number of rows replaced.
    """
    storage = storage or get_storage()
    settings = get_settings()
    async with get_session_factory()() as db:
        await set_tenant(db, tenant_id)
        rows = (
            await db.execute(
                select(
                    MediaEmbedding.id,
                    MediaEmbedding.media_id,
                    MediaEmbedding.model_id,
                    MediaEmbedding.phash,
                    MediaAsset.storage_key,
                )
                .join(MediaAsset, MediaAsset.id == MediaEmbedding.media_id)
                # Originals deleted by retention can't be re-hashed.
                .where(MediaAsset.original_purged_at.is_(None))
                .order_by(MediaEmbedding.media_id, MediaEmbedding.model_id)
            )
        ).all()
        await db.commit()
        hashes: dict[str, int] = {}
        stale = []
        for row in rows:
            if row.storage_key not in hashes:
                data = await storage.read(row.storage_key, max_bytes=settings.media_max_bytes)
                image = decode_upright(data, max_pixels=settings.media_max_pixels)
                hashes[row.storage_key] = await asyncio.to_thread(perceptual_hash, image)
            if hashes[row.storage_key] != row.phash:
                stale.append((row, hashes[row.storage_key]))
        for row, phash in stale:
            vector = await db.scalar(
                text("DELETE FROM media_embeddings WHERE id = :id RETURNING embedding::text"),
                {"id": row.id},
            )
            await db.execute(
                _INSERT_EMBEDDING,
                {
                    "tenant_id": tenant_id,
                    "media_id": row.media_id,
                    "model_id": row.model_id,
                    "embedding": vector,
                    "phash": to_signed64(phash),
                },
            )
        await db.commit()
    if stale:
        logger.info("perceptual hashes refreshed", extra=log_fields(count=len(stale)))
    return len(stale)


async def check_faces(
    media_id: uuid.UUID, tenant_id: uuid.UUID, *, storage: ObjectStorage | None = None
) -> int | None:
    """Publish a photo's public copies with every face blurred, once.

    With face blurring on, media processing verifies a photo and reads its
    metadata but stops at `processing` without making public copies
    (`process_asset`). This step renders the display and thumbnail copies
    from the original, with the faces the detector finds blurred, and only
    then marks the photo ready, so no unblurred public copy ever exists.
    A photo that was made ready while blurring was off is re-rendered the
    same way once blurring is on. The original is never altered.

    Returns the number of faces blurred, or None when there was nothing to
    do (already checked, not processed yet, or blurring off for a photo
    that is already public).
    """
    storage = storage or get_storage()
    settings = get_settings()
    async with get_session_factory()() as db:
        await set_tenant(db, tenant_id)
        asset = await db.scalar(select(MediaAsset).where(MediaAsset.id == media_id))
        if asset is None or asset.faces_checked_at is not None:
            return None
        held = asset.status == MediaStatus.PROCESSING and asset.processed_at is not None
        public_unchecked = asset.status == MediaStatus.READY and settings.face_blur_enabled
        if not (held or public_unchecked):
            return None
        original_key = asset.storage_key
        await db.rollback()

        try:
            detector = registry.get_face_detector()
        except Exception as exc:
            raise AIUnavailable(f"face detector unavailable: {exc!r}") from exc
        data = await storage.read(original_key, max_bytes=settings.media_max_bytes)

        def detect_and_render() -> tuple[int, dict[str, Variant]]:
            image = decode_upright(data, max_pixels=settings.media_max_pixels)
            source = Image.open(io.BytesIO(data))
            image.info.update(source.info)
            boxes = detector.detect(image)
            public = blur_regions(image, boxes) if boxes else image
            return len(boxes), render_image_variants(public)

        try:
            count, variants = await asyncio.to_thread(detect_and_render)
        except InvalidImage as exc:  # verified at upload, so this is unexpected
            raise AIUnavailable(f"undecodable photo: {exc.reason}") from exc
        keys = {name: object_key(tenant_id, media_id, f"{name}.webp") for name in variants}
        for name, variant in variants.items():
            await storage.write(keys[name], variant.data, content_type="image/webp")
        display = variants["display"]
        await db.execute(
            update(MediaAsset)
            .where(
                MediaAsset.id == media_id,
                MediaAsset.faces_checked_at.is_(None),
                MediaAsset.status.in_([MediaStatus.PROCESSING, MediaStatus.READY]),
            )
            .values(
                status=MediaStatus.READY,
                display_key=keys["display"],
                thumb_key=keys["thumb"],
                width=display.width,
                height=display.height,
                faces_checked_at=datetime.now(UTC),
                face_count=count,
            )
        )
        await db.commit()
    logger.info("faces checked", extra=log_fields(media_id=str(media_id), faces=count))
    return count


async def analyze_media(media_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    """The `analyze_media` task: the face check first, so the photo is
    published as soon as it can be, then its embedding and pHash."""
    await check_faces(media_id, tenant_id)
    return await ensure_embeddings(tenant_id, [media_id])
