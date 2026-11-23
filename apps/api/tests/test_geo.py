"""Reverse geocoding: PostGIS ward/zone lookup, the provider interface, the
Redis cache and Nominatim's rate limit. Nothing here touches the network:
the Nominatim tests use an in-process httpx transport."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domains.geo.geocoder import (
    GeocoderUnavailable,
    NominatimGeocoder,
    format_address,
    get_geocoder,
)
from tests.phase1 import NE, OUTSIDE, SW, City, make_city

REVERSE = "/api/v1/geo/reverse"


class FakeGeocoder:
    name = "fake"

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[float, float, str]] = []
        self.fail = fail

    async def reverse(self, lat: float, lng: float, *, locale: str) -> str | None:
        self.calls.append((lat, lng, locale))
        if self.fail:
            raise GeocoderUnavailable()
        return f"Somewhere near {lat:.4f},{lng:.4f}"


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


@pytest.fixture
def fake(app: FastAPI) -> Iterator[FakeGeocoder]:
    geocoder = FakeGeocoder()
    app.dependency_overrides[get_geocoder] = lambda: geocoder
    yield geocoder
    del app.dependency_overrides[get_geocoder]


async def _reverse(client: httpx.AsyncClient, city: City, lng: float, lat: float) -> dict:
    response = await client.get(
        REVERSE, params={"lat": lat, "lng": lng}, headers={"X-Tenant": city.tenant.slug}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_point_in_a_ward(client: httpx.AsyncClient, city: City, fake: FakeGeocoder) -> None:
    body = await _reverse(client, city, NE[0] + 0.00001, NE[1] + 0.00002)
    assert body["in_jurisdiction"] is True
    assert body["ward"] == {"id": str(city.wards["NE"]), "name": "Ward NE", "code": "W-NE"}
    assert body["zone"] == {"id": str(city.zones["N"]), "name": "ZN"}
    assert body["address_text"] == "Somewhere near 12.9900,77.6100"

    # A point within ~11 m is served from the cache.
    again = await _reverse(client, city, NE[0] + 0.00003, NE[1] + 0.00001)
    assert again["address_text"] == body["address_text"]
    assert fake.calls == [(12.99, 77.61, "en")]


async def test_point_outside_the_city(
    client: httpx.AsyncClient, city: City, fake: FakeGeocoder
) -> None:
    body = await _reverse(client, city, *OUTSIDE)
    assert body["in_jurisdiction"] is False
    assert body["ward"] is None
    assert body["zone"] is None
    assert body["address_text"] is not None  # the citizen can still see where they are


async def test_point_on_a_ward_boundary_gets_one_ward(
    client: httpx.AsyncClient, city: City, fake: FakeGeocoder
) -> None:
    body = await _reverse(client, city, 77.59, 12.97)  # where all four wards meet
    assert body["in_jurisdiction"] is True
    assert body["ward"]["code"] in {"W-NE", "W-NW", "W-SE", "W-SW"}
    assert (await _reverse(client, city, 77.59, 12.97))["ward"] == body["ward"]


async def test_failing_geocoder_still_answers(
    client: httpx.AsyncClient, app: FastAPI, city: City
) -> None:
    failing = FakeGeocoder(fail=True)
    app.dependency_overrides[get_geocoder] = lambda: failing
    try:
        body = await _reverse(client, city, *SW)
    finally:
        del app.dependency_overrides[get_geocoder]
    assert body["address_text"] is None
    assert body["ward"]["id"] == str(city.wards["SW"])


async def test_no_geocoder_configured(client: httpx.AsyncClient, city: City) -> None:
    # The suite runs with GEOCODER=none.
    body = await _reverse(client, city, *SW)
    assert body["address_text"] is None
    assert body["in_jurisdiction"] is True


async def test_reverse_needs_a_tenant_and_valid_coordinates(
    client: httpx.AsyncClient, city: City
) -> None:
    assert (await client.get(REVERSE, params={"lat": 12.9, "lng": 77.6})).status_code == 401
    signed_in = await client.get(
        REVERSE, params={"lat": SW[1], "lng": SW[0]}, headers=city.citizen.headers
    )
    assert signed_in.status_code == 200
    bad = await client.get(
        REVERSE, params={"lat": 91, "lng": 77.6}, headers={"X-Tenant": city.tenant.slug}
    )
    assert bad.status_code == 422


async def test_other_tenants_boundaries_are_ignored(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    other = await make_city(client, sms, owner_engine)
    body = await _reverse(client, other, *NE)
    assert body["ward"]["id"] == str(other.wards["NE"])
    assert body["ward"]["id"] != str(city.wards["NE"])


# --- tenant map view ---------------------------------------------------------------------


async def test_current_tenant_includes_the_map_view(client: httpx.AsyncClient, city: City) -> None:
    response = await client.get("/api/v1/tenants/current", headers={"X-Tenant": city.tenant.slug})
    assert response.status_code == 200
    view = response.json()["map"]
    assert view["bounds"] == [77.55, 12.93, 77.63, 13.01]
    assert view["center"] == pytest.approx([77.59, 12.97])
    assert view["zoom"] == 12  # 0.08 degrees across


async def test_map_view_is_null_without_geometry(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    from tests.factories import create_tenant

    async with owner_engine.begin() as conn:
        bare = await create_tenant(conn)
    response = await client.get("/api/v1/tenants/current", headers={"X-Tenant": bare.slug})
    assert response.json()["map"] is None


# --- the Nominatim provider, without the network ---------------------------------------

NOMINATIM_PAYLOAD = {
    "display_name": "MG Road, Shivajinagar, Bengaluru, Karnataka, 560001, India",
    "address": {
        "road": "MG Road",
        "suburb": "Shivajinagar",
        "city": "Bengaluru",
        "state": "Karnataka",
        "country": "India",
    },
}


def _provider(handler: Any, redis: Any, **kwargs: Any) -> NominatimGeocoder:
    return NominatimGeocoder(
        base_url="https://nominatim.invalid",
        user_agent="CivicPulse-API/0.1 (test)",
        timeout=1,
        redis=redis,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


async def test_nominatim_request_and_parsing(redis: Any) -> None:
    await redis.delete(NominatimGeocoder.SLOT_KEY)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=NOMINATIM_PAYLOAD)

    address = await _provider(handler, redis).reverse(12.97164, 77.59461, locale="hi")
    assert address == "MG Road, Shivajinagar, Bengaluru"
    request = seen[0]
    assert request.url.path == "/reverse"
    assert request.url.params["lat"] == "12.9716"
    assert request.url.params["lon"] == "77.5946"
    assert request.url.params["format"] == "jsonv2"
    assert request.url.params["accept-language"] == "hi"
    assert request.headers["user-agent"] == "CivicPulse-API/0.1 (test)"
    # Nothing about the caller is sent upstream.
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers


async def test_nominatim_failures_raise_unavailable(redis: Any) -> None:
    await redis.delete(NominatimGeocoder.SLOT_KEY)
    provider = _provider(lambda request: httpx.Response(503), redis)
    with pytest.raises(GeocoderUnavailable):
        await provider.reverse(12.9, 77.6, locale="en")


async def test_nominatim_is_kept_to_one_request_per_interval(redis: Any) -> None:
    await redis.delete(NominatimGeocoder.SLOT_KEY)
    stamps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        stamps.append(time.monotonic())
        return httpx.Response(200, json=NOMINATIM_PAYLOAD)

    provider = _provider(handler, redis, min_interval_ms=400)
    await provider.reverse(12.9, 77.6, locale="en")
    await provider.reverse(12.8, 77.5, locale="en")
    assert len(stamps) == 2
    assert stamps[1] - stamps[0] >= 0.35

    # With no time to wait for a slot, the lookup is skipped, not queued.
    impatient = _provider(handler, redis, min_interval_ms=5000, max_wait_seconds=0)
    await redis.delete(NominatimGeocoder.SLOT_KEY)
    await impatient.reverse(12.7, 77.4, locale="en")
    assert await impatient.reverse(12.6, 77.3, locale="en") is None
    assert len(stamps) == 3


def test_format_address_falls_back_to_display_name() -> None:
    assert format_address({"display_name": " Somewhere, India ", "address": {}}) == (
        "Somewhere, India"
    )
    assert format_address({"address": {"city": "Pune", "suburb": "Pune"}}) == "Pune"
    assert format_address({}) is None
