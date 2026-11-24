"""Per-photo analysis: embeddings and face blurring of the public copies."""

from __future__ import annotations

import io
import uuid
from typing import Any

import httpx
import numpy as np
import pytest
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.fake import make_scene
from app.core.storage import StorageError, get_storage
from app.domains.ai.analysis import analyze_media, check_faces
from app.domains.media.processing import AWAITING_FACE_CHECK, process_asset, render_variants
from app.domains.media.service import object_key
from tests.phase1 import City, make_city, upload
from tests.phase2 import report, view

FACE = (100, 80, 160, 160)  # x, y, width, height in the 640 x 480 scene


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


async def _keys(engine: AsyncEngine, media_id: str) -> Any:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT status, storage_key, display_key, faces_checked_at, face_count "
                    "FROM media_assets WHERE id = :m"
                ),
                {"m": media_id},
            )
        ).one()


def _region(data: bytes, box: tuple[int, int, int, int], scale: float) -> np.ndarray:
    image = Image.open(io.BytesIO(data)).convert("RGB")
    x, y, w, h = (int(v * scale) for v in box)
    return np.asarray(image.crop((x, y, x + w, y + h)), dtype=np.float64)


async def _exists(key: str) -> bool:
    try:
        await get_storage().read(key, max_bytes=10_000_000)
    except StorageError:
        return False
    return True


async def test_public_copies_appear_only_after_the_face_check(
    client: httpx.AsyncClient,
    owner_engine: AsyncEngine,
    city: City,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ai_face_blur", True)
    original = make_scene(31, faces=[FACE], image_format="PNG")
    media_id = (await upload(client, city.citizen, original, "image/png")).json()["id"]
    tenant = uuid.UUID(city.citizen.user["tenant_id"])

    # Verified and its metadata read, but no public copy exists yet: not in
    # storage, not as a URL, however the photo is reached.
    assert await process_asset(uuid.UUID(media_id), tenant) == AWAITING_FACE_CHECK
    row = await _keys(owner_engine, media_id)
    assert (row.status, row.display_key, row.faces_checked_at) == ("processing", None, None)
    display_key = object_key(tenant, uuid.UUID(media_id), "display.webp")
    assert not await _exists(display_key)
    submitted = await report(client, city, city.citizen, media_ids=[media_id])
    (photo,) = submitted["media"]
    assert (photo["status"], photo["thumb_url"], photo["display_url"]) == ("processing", None, None)
    # Processing it again (housekeeping re-queues stuck photos) changes nothing.
    assert await process_asset(uuid.UUID(media_id), tenant) == AWAITING_FACE_CHECK
    assert not await _exists(display_key)

    assert await analyze_media(uuid.UUID(media_id), tenant) == "fake-vision@1"
    row = await _keys(owner_engine, media_id)
    assert (row.status, row.display_key, row.face_count) == ("ready", display_key, 1)
    assert row.faces_checked_at is not None
    (photo,) = (await view(client, city.citizen, submitted["id"]))["media"]
    assert photo["status"] == "ready"
    assert photo["thumb_url"] is not None
    assert photo["display_url"] is not None

    # The face is blurred in the copy that was published, and the rest of
    # the scene is as an unblurred rendering would have it.
    storage = get_storage()
    published = await storage.read(display_key, max_bytes=10_000_000)
    plain = render_variants(original, max_pixels=settings.media_max_pixels)["display"].data
    sharp, blurred = _region(plain, FACE, 1.0), _region(published, FACE, 1.0)
    assert blurred.std() < 0.6 * sharp.std()
    corner = (500, 380, 100, 80)
    assert np.abs(_region(plain, corner, 1.0) - _region(published, corner, 1.0)).mean() < 3
    # The original is never touched.
    assert await storage.read(row.storage_key, max_bytes=10_000_000) == original

    # Done once.
    assert await check_faces(uuid.UUID(media_id), tenant) is None


async def test_without_blurring_photos_are_public_as_soon_as_processed(
    client: httpx.AsyncClient,
    owner_engine: AsyncEngine,
    city: City,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = uuid.UUID(city.citizen.user["tenant_id"])
    monkeypatch.setattr(settings, "ai_face_blur", False)
    with_face = (
        await upload(
            client, city.citizen, make_scene(32, faces=[FACE], image_format="PNG"), "image/png"
        )
    ).json()["id"]
    assert await process_asset(uuid.UUID(with_face), tenant) == "ready"
    assert await check_faces(uuid.UUID(with_face), tenant) is None
    assert (await _keys(owner_engine, with_face)).faces_checked_at is None

    # Switched on later: a photo that is already public is re-rendered.
    monkeypatch.setattr(settings, "ai_face_blur", True)
    assert await check_faces(uuid.UUID(with_face), tenant) == 1
    assert (await _keys(owner_engine, with_face)).status == "ready"

    plain = (await upload(client, city.citizen, make_scene(33))).json()["id"]
    assert await process_asset(uuid.UUID(plain), tenant) == AWAITING_FACE_CHECK
    assert await check_faces(uuid.UUID(plain), tenant) == 0
    row = await _keys(owner_engine, plain)
    assert (row.status, row.face_count) == ("ready", 0)


async def test_a_photo_still_processing_is_embedded_but_not_blurred_yet(
    client: httpx.AsyncClient,
    owner_engine: AsyncEngine,
    city: City,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ai_face_blur", True)
    tenant = uuid.UUID(city.citizen.user["tenant_id"])
    media_id = (
        await upload(
            client, city.citizen, make_scene(34, faces=[FACE], image_format="PNG"), "image/png"
        )
    ).json()["id"]
    await analyze_media(uuid.UUID(media_id), tenant)
    async with owner_engine.connect() as conn:
        embedded = await conn.scalar(
            text("SELECT count(*) FROM media_embeddings WHERE media_id = :m"), {"m": media_id}
        )
    assert embedded == 1
    assert (await _keys(owner_engine, media_id)).faces_checked_at is None
