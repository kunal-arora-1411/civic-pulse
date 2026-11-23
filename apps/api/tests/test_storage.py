"""The S3 storage client against the compose MinIO.

These pin down the properties the upload flow relies on: URLs are signed for
the public endpoint, and storage itself enforces the signed Content-Type and
Content-Length, so a client can't swap the file type or upload more bytes
than it declared.
"""

from __future__ import annotations

import uuid
from urllib.parse import urlsplit

import httpx
import pytest

from app.core.config import get_settings
from app.core.storage import ObjectTooLarge, S3Storage, get_storage


def _key() -> str:
    return f"tests/storage/{uuid.uuid4().hex}"


async def test_presigned_put_and_get_round_trip() -> None:
    storage = get_storage()
    key, data = _key(), b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    url = storage.presign_put(
        key, content_type="image/png", content_length=len(data), expires_in=60
    )
    async with httpx.AsyncClient() as http:
        put = await http.put(
            url,
            content=data,
            headers={"Content-Type": "image/png", "Origin": "http://localhost:3000"},
        )
        assert put.status_code == 200, put.text
        # MinIO's CORS answers the web origin on the actual request too.
        assert put.headers.get("access-control-allow-origin") == "http://localhost:3000"

        head = await storage.head(key)
        assert head is not None
        assert head.size == len(data)
        assert head.content_type == "image/png"

        got = await http.get(storage.presign_get(key, expires_in=60))
        assert got.status_code == 200
        assert got.content == data
    assert await storage.read(key, max_bytes=1024) == data
    with pytest.raises(ObjectTooLarge):
        await storage.read(key, max_bytes=8)

    await storage.delete([key, _key()])  # missing keys are fine
    assert await storage.head(key) is None


@pytest.mark.parametrize(
    ("content_type", "extra"),
    [("image/png", b"more bytes than declared"), ("text/html", b"")],
)
async def test_storage_enforces_the_signed_type_and_size(content_type: str, extra: bytes) -> None:
    storage = get_storage()
    key, data = _key(), b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    url = storage.presign_put(
        key, content_type="image/png", content_length=len(data), expires_in=60
    )
    async with httpx.AsyncClient() as http:
        put = await http.put(url, content=data + extra, headers={"Content-Type": content_type})
    assert put.status_code == 403
    assert await storage.head(key) is None


def test_urls_are_signed_for_the_public_endpoint() -> None:
    settings = get_settings().model_copy(
        update={"s3_endpoint": "http://minio:9000", "s3_public_endpoint": "https://media.example"}
    )
    storage = S3Storage(settings)
    for url in (
        storage.presign_get("a/b", expires_in=600),
        storage.presign_put("a/b", content_type="image/jpeg", content_length=1, expires_in=600),
    ):
        parts = urlsplit(url)
        assert f"{parts.scheme}://{parts.netloc}" == "https://media.example"
        assert parts.path == f"/{settings.s3_bucket}/a/b"
        assert "X-Amz-Expires=600" in parts.query
