"""Direct-to-storage uploads against the compose MinIO: create, PUT, complete,
and every way verification can fail."""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.storage import get_storage
from tests import images
from tests.phase1 import City, login_new, make_city, put_to_storage, upload

UPLOADS = "/api/v1/media/uploads"


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


def _create_body(data: bytes, content_type: str = "image/jpeg", **overrides: Any) -> dict:
    return {
        "purpose": "report_evidence",
        "content_type": content_type,
        "size_bytes": len(data),
        "checksum_sha256": images.sha256(data),
        **overrides,
    }


async def _asset_row(engine: AsyncEngine, asset_id: str) -> Any:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT status, failure_reason, storage_key, exif, size_bytes "
                    "FROM media_assets WHERE id = :id"
                ),
                {"id": asset_id},
            )
        ).one()


async def test_upload_happy_path(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City, settings: Any
) -> None:
    data = images.jpeg((640, 480))
    created = await client.post(UPLOADS, headers=city.citizen.headers, json=_create_body(data))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["method"] == "PUT"
    assert body["headers"] == {"Content-Type": "image/jpeg"}
    assert body["expires_in"] == 600
    assert body["max_size_bytes"] == 10 * 1024 * 1024
    url = urlsplit(body["url"])
    assert f"{url.scheme}://{url.netloc}" == settings.s3_presign_endpoint
    assert str(city.tenant.id) in url.path  # keys are namespaced by tenant

    put = await put_to_storage(body["url"], data, "image/jpeg")
    assert put.status_code == 200
    assert put.headers["access-control-allow-origin"] == "http://localhost:3000"

    complete_url = f"{UPLOADS}/{body['upload_id']}/complete"
    completed = await client.post(complete_url, headers=city.citizen.headers)
    assert completed.status_code == 200, completed.text
    asset = completed.json()
    assert asset["id"] == body["upload_id"]
    assert asset["status"] == "processing"
    assert asset["content_type"] == "image/jpeg"
    assert (asset["width"], asset["height"]) == (640, 480)
    assert asset["variants"] == {"thumb": None, "display": None}
    # The EXIF time has no offset, so it is read as Asia/Kolkata.
    assert asset["captured_at"] == "2026-11-20T09:30:00+05:30"

    row = await _asset_row(owner_engine, asset["id"])
    assert row.status == "processing"
    assert row.size_bytes == len(data)
    assert row.exif["gps"] == pytest.approx(images.GPS, abs=1e-4)
    assert row.exif["make"] == "SyntheticCam"
    assert "gps" not in completed.text  # private metadata never leaves the API

    again = await client.post(complete_url, headers=city.citizen.headers)
    assert again.status_code == 200
    assert again.json()["id"] == asset["id"]


async def test_rotated_photos_report_displayed_dimensions(
    client: httpx.AsyncClient, city: City
) -> None:
    response = await upload(client, city.citizen, images.jpeg((640, 480), orientation=6))
    assert response.status_code == 200, response.text
    assert (response.json()["width"], response.json()["height"]) == (480, 640)


@pytest.mark.parametrize(
    ("data", "content_type"),
    [(images.png(), "image/png"), (images.webp(), "image/webp")],
)
async def test_png_and_webp_are_accepted(
    client: httpx.AsyncClient, city: City, data: bytes, content_type: str
) -> None:
    response = await upload(client, city.citizen, data, content_type)
    assert response.status_code == 200, response.text
    assert response.json()["content_type"] == content_type


async def _expect_rejected(
    client: httpx.AsyncClient,
    owner_engine: AsyncEngine,
    city: City,
    response: httpx.Response,
    reason: str,
) -> None:
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "upload_verification_failed"
    assert error["details"] == {"reason": reason}

    asset_id = str(response.request.url).split("/")[-2]
    row = await _asset_row(owner_engine, asset_id)
    assert row.status == "failed"
    assert row.failure_reason == reason
    assert await get_storage().head(row.storage_key) is None  # object deleted

    retry = await client.post(f"{UPLOADS}/{asset_id}/complete", headers=city.citizen.headers)
    assert retry.status_code == 422


async def test_spoofed_content_type_is_rejected(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    # JPEG bytes declared (and PUT, with a matching signature) as PNG.
    response = await upload(client, city.citizen, images.jpeg(), "image/png")
    await _expect_rejected(client, owner_engine, city, response, "content_type_mismatch")


async def test_non_image_bytes_are_rejected(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    payload = b"<html><script>alert(1)</script></html>"
    response = await upload(client, city.citizen, payload, "image/jpeg")
    await _expect_rejected(client, owner_engine, city, response, "not_an_image")


async def test_truncated_image_is_rejected(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    response = await upload(client, city.citizen, images.png()[:60], "image/png")
    await _expect_rejected(client, owner_engine, city, response, "not_an_image")


async def test_decompression_bomb_is_rejected(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    response = await upload(client, city.citizen, images.bomb(), "image/png")
    await _expect_rejected(client, owner_engine, city, response, "image_too_large")


async def test_checksum_mismatch_is_rejected(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    response = await upload(client, city.citizen, images.jpeg(), checksum="ab" * 32)
    await _expect_rejected(client, owner_engine, city, response, "checksum_mismatch")


async def test_completing_without_uploading_is_rejected(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    created = await client.post(
        UPLOADS, headers=city.citizen.headers, json=_create_body(images.jpeg())
    )
    response = await client.post(
        f"{UPLOADS}/{created.json()['upload_id']}/complete", headers=city.citizen.headers
    )
    await _expect_rejected(client, owner_engine, city, response, "object_missing")


async def test_storage_refuses_a_bigger_body_than_declared(
    client: httpx.AsyncClient, city: City
) -> None:
    data = images.jpeg()
    created = await client.post(UPLOADS, headers=city.citizen.headers, json=_create_body(data))
    put = await put_to_storage(created.json()["url"], data + b"\x00" * 1024, "image/jpeg")
    assert put.status_code == 403


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"size_bytes": 10 * 1024 * 1024 + 1}, "file_too_large"),
        ({"content_type": "image/gif"}, "unsupported_media_type"),
        ({"content_type": "application/pdf"}, "unsupported_media_type"),
        ({"content_type": "image/svg+xml"}, "unsupported_media_type"),
        ({"size_bytes": 0}, "validation_error"),
        ({"checksum_sha256": "not-hex"}, "validation_error"),
        ({"purpose": "avatar"}, "validation_error"),
    ],
)
async def test_create_rejects_bad_declarations(
    client: httpx.AsyncClient, city: City, overrides: dict, code: str
) -> None:
    body = _create_body(images.jpeg(), **overrides)
    response = await client.post(UPLOADS, headers=city.citizen.headers, json=body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == code


async def test_unfinished_uploads_are_capped_per_user(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    citizen = await login_new(client, sms, owner_engine, city, "citizen")
    body = _create_body(images.jpeg())
    for _ in range(20):
        assert (await client.post(UPLOADS, headers=citizen.headers, json=body)).status_code == 201
    capped = await client.post(UPLOADS, headers=citizen.headers, json=body)
    assert capped.status_code == 429
    assert capped.json()["error"]["code"] == "too_many_uploads"

    # Expired upload URLs stop counting.
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE media_assets SET upload_expires_at = now() - interval '1 second' "
                "WHERE owner_id = :o"
            ),
            {"o": citizen.user["id"]},
        )
    assert (await client.post(UPLOADS, headers=citizen.headers, json=body)).status_code == 201


async def test_only_the_owner_can_complete_an_upload(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    created = await client.post(
        UPLOADS, headers=city.citizen.headers, json=_create_body(images.jpeg())
    )
    other = await login_new(client, sms, owner_engine, city, "citizen")
    url = f"{UPLOADS}/{created.json()['upload_id']}/complete"
    assert (await client.post(url, headers=other.headers)).status_code == 404
    assert (
        await client.post(f"{UPLOADS}/{uuid.uuid4()}/complete", headers=other.headers)
    ).status_code == 404


async def test_upload_permissions(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    body = _create_body(images.jpeg())
    assert (await client.post(UPLOADS, json=body)).status_code == 401
    # Operators review issues; they don't submit evidence.
    assert (await client.post(UPLOADS, headers=city.operator.headers, json=body)).status_code == 403
    field_worker = await login_new(client, sms, owner_engine, city, "field_worker")
    assert (await client.post(UPLOADS, headers=field_worker.headers, json=body)).status_code == 201
