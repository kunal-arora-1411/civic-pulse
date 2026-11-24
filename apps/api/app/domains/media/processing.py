"""Turning a verified original into the variants people actually see.

`display` (longest side 1600 px) and `thumb` (400 px) are WebP files built
from decoded pixels only: the image is re-created from raw pixel data before
encoding, so no EXIF, XMP, ICC profile or comment from the original can ride
along. EXIF orientation is applied first, because the variants carry no tag
to say how to rotate them.
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from PIL import Image, ImageOps
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.db import get_session_factory
from app.core.logging import log_fields
from app.core.storage import ObjectStorage, get_storage
from app.core.tenancy import set_tenant
from app.domains.media.inspect import InvalidImage, open_image, read_exif
from app.domains.media.models import MediaAsset, MediaStatus
from app.domains.media.service import object_key

logger = logging.getLogger(__name__)

VARIANTS = {"display": (1600, 82), "thumb": (400, 75)}  # name: (longest side, WebP quality)


@dataclass(frozen=True, slots=True)
class Variant:
    data: bytes
    width: int
    height: int


def decode_upright(data: bytes, *, max_pixels: int) -> Image.Image:
    """Decode `data` in full with EXIF orientation applied. Raises InvalidImage."""
    image = open_image(data, max_pixels=max_pixels)
    try:
        image = ImageOps.exif_transpose(image)
        image.load()
    except InvalidImage:
        raise
    except Exception:
        raise InvalidImage("decode_failed") from None
    return image


def render_variants(data: bytes, *, max_pixels: int) -> dict[str, Variant]:
    """Decode `data` in full and encode each variant. Raises InvalidImage."""
    return render_image_variants(decode_upright(data, max_pixels=max_pixels))


def render_image_variants(image: Image.Image) -> dict[str, Variant]:
    """Encode each variant from an upright, decoded image (face blurring
    re-renders the variants from a blurred copy this way)."""
    has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
    mode = "RGBA" if has_alpha else "RGB"
    base = image.convert(mode)

    variants: dict[str, Variant] = {}
    for name, (side, quality) in VARIANTS.items():
        resized = base.copy()
        resized.thumbnail((side, side), Image.Resampling.LANCZOS)
        # A fresh image from raw pixels has an empty `info`, so nothing from
        # the original's metadata can be written out by the encoder.
        clean = Image.frombytes(mode, resized.size, resized.tobytes())
        buffer = io.BytesIO()
        clean.save(buffer, "WEBP", quality=quality, method=4)
        variants[name] = Variant(buffer.getvalue(), clean.width, clean.height)
    return variants


async def process_asset(
    asset_id: uuid.UUID, tenant_id: uuid.UUID, storage: ObjectStorage | None = None
) -> str:
    """Make the variants for one asset and mark it ready (or failed).

    Safe to run more than once: only `processing` assets are touched, the
    variant keys are deterministic, and the final update is conditional on
    the status still being `processing`. Storage errors propagate so the
    Celery task can retry; bad image data fails the asset for good.
    """
    storage = storage or get_storage()
    settings = get_settings()

    async with get_session_factory()() as db:
        await set_tenant(db, tenant_id)
        asset = await db.scalar(select(MediaAsset).where(MediaAsset.id == asset_id))
        if asset is None:
            logger.warning("media asset not found", extra=log_fields(media_id=str(asset_id)))
            return "missing"
        if asset.status != MediaStatus.PROCESSING:
            return asset.status
        original_key = asset.storage_key
        await db.rollback()  # don't hold a transaction open while decoding

        data = await storage.read(original_key, max_bytes=settings.media_max_bytes)
        values: dict[str, object]
        try:
            variants = await asyncio.to_thread(
                render_variants, data, max_pixels=settings.media_max_pixels
            )
            image = open_image(data, max_pixels=settings.media_max_pixels)
            exif = read_exif(image, tz=settings.local_timezone)
        except InvalidImage as exc:
            values = {"status": MediaStatus.FAILED, "failure_reason": exc.reason}
        else:
            keys = {name: object_key(tenant_id, asset_id, f"{name}.webp") for name in variants}
            for name, variant in variants.items():
                await storage.write(keys[name], variant.data, content_type="image/webp")
            display = variants["display"]
            values = {
                "status": MediaStatus.READY,
                "display_key": keys["display"],
                "thumb_key": keys["thumb"],
                "width": display.width,
                "height": display.height,
                "exif": exif.private or None,
                "captured_at": exif.captured_at,
                "processed_at": datetime.now(UTC),
            }

        result = await db.execute(
            update(MediaAsset)
            .where(MediaAsset.id == asset_id, MediaAsset.status == MediaStatus.PROCESSING)
            .values(**values)
            .returning(MediaAsset.status)
        )
        status = result.scalar_one_or_none()
        await db.commit()

    logger.info(
        "media processed",
        extra=log_fields(media_id=str(asset_id), status=values["status"], applied=status),
    )
    return str(values["status"])
