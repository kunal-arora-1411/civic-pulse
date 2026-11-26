"""Per-address limits on the unauthenticated endpoints (PRD 12.3, P6-07).

Each test talks from an address of its own, so the counters don't leak
into the rest of the suite, which runs everything from 127.0.0.1.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from tests.factories import TenantRow


@pytest.fixture
async def remote(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    # TEST-NET-3 plus a random last pair of octets: unique per test.
    octets = uuid.uuid4().bytes
    address = f"203.0.{octets[0]}.{octets[1]}"
    transport = httpx.ASGITransport(app=app, client=(address, 4321))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def test_otp_verify_is_limited_per_address(
    remote: httpx.AsyncClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "otp_verify_max_per_ip_per_hour", 3)
    body = {"challenge_id": str(uuid.uuid4()), "code": "123456"}
    statuses = [
        (await remote.post("/api/v1/auth/otp/verify", json=body)).status_code for _ in range(4)
    ]
    # Unknown challenges fail normally until the address runs out.
    assert 429 not in statuses[:3]
    assert statuses[3] == 429
    response = await remote.post("/api/v1/auth/otp/verify", json=body)
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["retry-after"]) > 0


async def test_refresh_is_limited_per_address(
    remote: httpx.AsyncClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "refresh_max_per_ip_per_hour", 2)
    statuses = [
        (
            await remote.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-token"})
        ).status_code
        for _ in range(3)
    ]
    assert statuses == [401, 401, 429]


async def test_mfa_verify_is_limited_per_address(
    remote: httpx.AsyncClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mfa_verify_max_per_ip_per_hour", 1)
    body = {"mfa_token": "not-a-token", "code": "123456"}
    first = await remote.post("/api/v1/auth/mfa/verify", json=body)
    second = await remote.post("/api/v1/auth/mfa/verify", json=body)
    assert first.status_code != 429
    assert second.status_code == 429


async def test_tenant_lookup_is_limited_per_address(
    remote: httpx.AsyncClient,
    tenant: TenantRow,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "tenant_lookup_max_per_ip_per_minute", 2)
    headers = {"X-Tenant": tenant.slug}
    statuses = [
        (await remote.get("/api/v1/tenants/current", headers=headers)).status_code for _ in range(3)
    ]
    assert statuses == [200, 200, 429]


async def test_addresses_are_counted_separately(
    app: FastAPI, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "refresh_max_per_ip_per_hour", 1)
    body = {"refresh_token": "not-a-token"}
    first = uuid.uuid4().bytes[0]
    for last in (first, first ^ 1):
        transport = httpx.ASGITransport(app=app, client=(f"198.51.100.{last}", 1))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            assert (await c.post("/api/v1/auth/refresh", json=body)).status_code == 401
