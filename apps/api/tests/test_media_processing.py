"""Media processing: WebP variants with every bit of metadata removed,
private EXIF capture, and failure handling."""

from __future__ import annotations

import io
import uuid
from typing import Any

import httpx
import pytest
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.storage import get_storage
from app.domains.media.processing import process_asset
from app.domains.media.tasks import process_media
from app.worker import celery_app
from tests import images
from tests.helpers import RecordingMediaQueue
from tests.phase1 import City, make_city, upload


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


async def _row(engine: AsyncEngine, asset_id: str) -> Any:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT status, failure_reason, display_key, thumb_key, width, height, exif, "
                    "captured_at, storage_key FROM media_assets WHERE id = :id"
                ),
                {"id": asset_id},
            )
        ).one()


def _assert_no_metadata(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    assert image.format == "WEBP"
    assert len(image.getexif()) == 0
    for key in ("exif", "xmp", "icc_profile", "comment"):
        assert key not in image.info, key
    # Belt and braces: no EXIF block or camera string anywhere in the file.
    assert b"Exif" not in data
    assert b"SyntheticCam" not in data
    assert b"GPS" not in data
    return image


async def test_completion_queues_processing(
    client: httpx.AsyncClient, city: City, media_queue: RecordingMediaQueue
) -> None:
    response = await upload(client, city.citizen, images.jpeg())
    asset_id = uuid.UUID(response.json()["id"])
    assert (asset_id, city.tenant.id) in media_queue.queued


async def test_processing_makes_stripped_webp_variants(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    # Landscape pixels with orientation 6: displayed as portrait.
    response = await upload(client, city.citizen, images.jpeg((2400, 1800), orientation=6))
    asset_id = response.json()["id"]

    assert await process_asset(uuid.UUID(asset_id), city.tenant.id) == "ready"

    row = await _row(owner_engine, asset_id)
    assert row.status == "ready"
    assert (row.width, row.height) == (1200, 1600)  # display variant, rotated
    # The private copy of the metadata is kept.
    assert row.exif["gps"] == pytest.approx(images.GPS, abs=1e-4)
    assert row.exif["orientation"] == 6
    assert row.captured_at is not None

    storage = get_storage()
    display = _assert_no_metadata(await storage.read(row.display_key, max_bytes=10_000_000))
    thumb = _assert_no_metadata(await storage.read(row.thumb_key, max_bytes=10_000_000))
    assert display.size == (1200, 1600)
    assert max(thumb.size) == 400
    assert thumb.size == (300, 400)

    # The original is untouched and still has its EXIF (staff-only).
    original = await storage.read(row.storage_key, max_bytes=10_000_000)
    assert Image.open(io.BytesIO(original)).getexif().get(0x0112) == 6

    # Running it again (a redelivered task) changes nothing.
    assert await process_asset(uuid.UUID(asset_id), city.tenant.id) == "ready"


async def test_png_with_alpha_keeps_transparency(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    response = await upload(client, city.citizen, images.png(), "image/png")
    asset_id = response.json()["id"]
    assert await process_asset(uuid.UUID(asset_id), city.tenant.id) == "ready"
    row = await _row(owner_engine, asset_id)
    display = await get_storage().read(row.display_key, max_bytes=10_000_000)
    assert _assert_no_metadata(display).mode == "RGBA"


async def test_ready_assets_get_signed_variant_urls(client: httpx.AsyncClient, city: City) -> None:
    response = await upload(client, city.citizen, images.jpeg())
    asset_id = response.json()["id"]
    await process_asset(uuid.UUID(asset_id), city.tenant.id)

    again = await client.post(
        f"/api/v1/media/uploads/{asset_id}/complete", headers=city.citizen.headers
    )
    body = again.json()
    assert body["status"] == "ready"
    async with httpx.AsyncClient() as http:
        for name in ("thumb", "display"):
            fetched = await http.get(body["variants"][name])
            assert fetched.status_code == 200
            assert fetched.headers["content-type"] == "image/webp"


async def test_undecodable_pixels_fail_the_asset(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    data = images.jpeg((800, 600), exif=False)
    response = await upload(client, city.citizen, data)
    asset_id = response.json()["id"]
    row = await _row(owner_engine, asset_id)
    # Keep the JPEG header (so it still opens) but cut the scan data short.
    corrupted = data[: len(data) // 2]
    await get_storage().write(row.storage_key, corrupted, content_type="image/jpeg")

    assert await process_asset(uuid.UUID(asset_id), city.tenant.id) == "failed"
    row = await _row(owner_engine, asset_id)
    assert row.status == "failed"
    assert row.failure_reason == "decode_failed"
    assert row.display_key is None


async def test_processing_only_touches_its_own_tenant(
    client: httpx.AsyncClient, city: City, sms: Any, owner_engine: AsyncEngine
) -> None:
    response = await upload(client, city.citizen, images.jpeg())
    other = await make_city(client, sms, owner_engine)
    # Under another tenant's context the asset is invisible.
    assert await process_asset(uuid.UUID(response.json()["id"]), other.tenant.id) == "missing"


def test_processing_task_is_registered() -> None:
    assert process_media.name == "civicpulse.media.process"
    assert "civicpulse.media.process" in celery_app.tasks
