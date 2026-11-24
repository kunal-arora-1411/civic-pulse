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
from app.core.storage import get_storage
from app.domains.ai.analysis import analyze_media, blur_faces
from app.domains.media.processing import process_asset
from tests.phase1 import City, make_city, upload

FACE = (100, 80, 160, 160)  # x, y, width, height in the 640 x 480 scene


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


async def _keys(engine: AsyncEngine, media_id: str) -> Any:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT storage_key, display_key, faces_checked_at, face_count "
                    "FROM media_assets WHERE id = :m"
                ),
                {"m": media_id},
            )
        ).one()


def _region(data: bytes, box: tuple[int, int, int, int], scale: float) -> np.ndarray:
    image = Image.open(io.BytesIO(data)).convert("RGB")
    x, y, w, h = (int(v * scale) for v in box)
    return np.asarray(image.crop((x, y, x + w, y + h)), dtype=np.float64)


async def test_faces_are_blurred_in_the_public_copies_only(
    client: httpx.AsyncClient,
    owner_engine: AsyncEngine,
    city: City,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ai_face_blur", True)
    original = make_scene(31, faces=[FACE], image_format="PNG")
    response = await upload(client, city.citizen, original, "image/png")
    media_id = response.json()["id"]
    tenant = uuid.UUID(city.citizen.user["tenant_id"])
    assert await process_asset(uuid.UUID(media_id), tenant) == "ready"
    storage = get_storage()
    row = await _keys(owner_engine, media_id)
    before = await storage.read(row.display_key, max_bytes=10_000_000)

    assert await analyze_media(uuid.UUID(media_id), tenant) == "fake-vision@1"
    row = await _keys(owner_engine, media_id)
    assert row.face_count == 1
    assert row.faces_checked_at is not None
    after = await storage.read(row.display_key, max_bytes=10_000_000)
    # The display copy is the full 640 px wide scene: the face area is now
    # smoothed (much less variation), the rest is as it was.
    sharp, blurred = _region(before, FACE, 1.0), _region(after, FACE, 1.0)
    assert blurred.std() < 0.6 * sharp.std()
    corner = (500, 380, 100, 80)
    assert np.abs(_region(before, corner, 1.0) - _region(after, corner, 1.0)).mean() < 3
    # The original is never touched.
    assert await storage.read(row.storage_key, max_bytes=10_000_000) == original

    # Done once.
    assert await blur_faces(uuid.UUID(media_id), tenant) is None


async def test_nothing_is_blurred_when_switched_off_or_without_faces(
    client: httpx.AsyncClient,
    owner_engine: AsyncEngine,
    city: City,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = uuid.UUID(city.citizen.user["tenant_id"])
    with_face = (
        await upload(
            client, city.citizen, make_scene(32, faces=[FACE], image_format="PNG"), "image/png"
        )
    ).json()["id"]
    await process_asset(uuid.UUID(with_face), tenant)
    monkeypatch.setattr(settings, "ai_face_blur", False)
    assert await blur_faces(uuid.UUID(with_face), tenant) is None
    assert (await _keys(owner_engine, with_face)).faces_checked_at is None

    monkeypatch.setattr(settings, "ai_face_blur", True)
    plain = (await upload(client, city.citizen, make_scene(33))).json()["id"]
    await process_asset(uuid.UUID(plain), tenant)
    assert await blur_faces(uuid.UUID(plain), tenant) == 0
    assert (await _keys(owner_engine, plain)).face_count == 0


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
