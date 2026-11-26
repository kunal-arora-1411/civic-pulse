"""Malware scanning of uploads (P6-07) against an in-process fake clamd
that speaks the real INSTREAM wire protocol."""

from __future__ import annotations

import asyncio
import struct
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.storage import get_storage
from app.domains.media.scan import ScannerUnavailable, parse_reply, scan_bytes
from tests import images
from tests.phase1 import City, make_city, upload
from tests.test_media_uploads import _asset_row

UPLOADS = "/api/v1/media/uploads"


@dataclass
class FakeClamd:
    port: int
    verdict: bytes = b"stream: OK\0"
    received: list[bytes] = field(default_factory=list)


async def _serve(fake: FakeClamd, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    command = await reader.readuntil(b"\0")
    assert command == b"zINSTREAM\0"
    data = bytearray()
    while True:
        (length,) = struct.unpack("!I", await reader.readexactly(4))
        if length == 0:
            break
        data += await reader.readexactly(length)
    fake.received.append(bytes(data))
    writer.write(fake.verdict)
    await writer.drain()
    writer.close()


@pytest.fixture
async def clamd() -> AsyncIterator[FakeClamd]:
    fake = FakeClamd(port=0)
    server = await asyncio.start_server(lambda r, w: _serve(fake, r, w), host="127.0.0.1", port=0)
    fake.port = server.sockets[0].getsockname()[1]
    async with server:
        yield fake


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


def _use_scanner(monkeypatch: pytest.MonkeyPatch, settings: Settings, port: int) -> None:
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", port)
    monkeypatch.setattr(settings, "clamav_timeout_seconds", 5.0)


def test_replies_are_parsed() -> None:
    assert parse_reply(b"stream: OK\0").clean
    found = parse_reply(b"stream: Win.Test.EICAR_HDB-1 FOUND\0")
    assert not found.clean
    assert found.signature == "Win.Test.EICAR_HDB-1"
    with pytest.raises(ScannerUnavailable):
        parse_reply(b"INSTREAM size limit exceeded. ERROR\0")
    with pytest.raises(ScannerUnavailable):
        parse_reply(b"")


async def test_large_files_are_streamed_in_chunks(clamd: FakeClamd) -> None:
    data = bytes(range(256)) * 1024  # 256 KiB: several chunks
    result = await scan_bytes(data, host="127.0.0.1", port=clamd.port, time_limit=5)
    assert result.clean
    assert clamd.received == [data]


async def test_unreachable_scanner_is_an_error_not_a_pass(clamd: FakeClamd) -> None:
    # A port nothing listens on: bind one, then close it.
    server = await asyncio.start_server(lambda r, w: None, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    with pytest.raises(ScannerUnavailable):
        await scan_bytes(b"x", host="127.0.0.1", port=port, time_limit=2)


async def test_clean_upload_is_scanned_and_accepted(
    client: httpx.AsyncClient,
    city: City,
    clamd: FakeClamd,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_scanner(monkeypatch, settings, clamd.port)
    data = images.jpeg()
    response = await upload(client, city.citizen, data)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "processing"
    assert clamd.received == [data]


async def test_infected_upload_is_rejected_and_deleted(
    client: httpx.AsyncClient,
    owner_engine: AsyncEngine,
    city: City,
    clamd: FakeClamd,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_scanner(monkeypatch, settings, clamd.port)
    clamd.verdict = b"stream: Win.Test.EICAR_HDB-1 FOUND\0"
    response = await upload(client, city.citizen, images.jpeg())
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "upload_verification_failed"
    assert error["details"] == {"reason": "malware_detected"}

    asset_id = str(response.request.url).split("/")[-2]
    row = await _asset_row(owner_engine, asset_id)
    assert (row.status, row.failure_reason) == ("failed", "malware_detected")
    assert await get_storage().head(row.storage_key) is None


async def test_scanner_outage_fails_closed_and_can_be_retried(
    client: httpx.AsyncClient,
    owner_engine: AsyncEngine,
    city: City,
    clamd: FakeClamd,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = await asyncio.start_server(lambda r, w: None, host="127.0.0.1", port=0)
    dead_port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    _use_scanner(monkeypatch, settings, dead_port)

    response = await upload(client, city.citizen, images.jpeg())
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "service_unavailable"
    asset_id = str(response.request.url).split("/")[-2]
    row = await _asset_row(owner_engine, asset_id)
    assert row.status == "pending"
    assert await get_storage().head(row.storage_key) is not None

    # The scanner comes back: completing the same upload now works.
    monkeypatch.setattr(settings, "clamav_port", clamd.port)
    retried = await client.post(f"{UPLOADS}/{asset_id}/complete", headers=city.citizen.headers)
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "processing"


async def test_scanning_is_off_without_a_host(
    client: httpx.AsyncClient, city: City, clamd: FakeClamd, settings: Settings
) -> None:
    assert settings.clamav_host == ""
    response = await upload(client, city.citizen, images.jpeg())
    assert response.status_code == 200
    assert clamd.received == []
