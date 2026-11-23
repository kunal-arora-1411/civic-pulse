"""Reverse geocoding behind a provider interface (PRD FR-011).

Only the human-readable address comes from here. Whether a point is inside
the municipality, and which ward and zone it falls in, is answered by
PostGIS from our own boundaries (app/domains/geo/service.py), so it works
the same with the geocoder switched off or down.

Every failure degrades to "no address": the caller still gets a 200 with
`address_text: null`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from functools import lru_cache
from typing import Annotated, Any, Protocol

import httpx
from fastapi import Depends
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.logging import log_fields
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

# 4 decimal places is about 11 m at the equator (less east-west in India).
PRECISION = 4
_MISS = ""  # cached marker for "looked up, nothing found"


class Geocoder(Protocol):
    name: str

    async def reverse(self, lat: float, lng: float, *, locale: str) -> str | None: ...


class NoGeocoder:
    name = "none"

    async def reverse(self, lat: float, lng: float, *, locale: str) -> str | None:
        return None


def format_address(payload: dict[str, Any]) -> str | None:
    """A short "road, area, city" line from a Nominatim jsonv2 response."""
    address = payload.get("address") or {}

    def first(*keys: str) -> str | None:
        for key in keys:
            value = address.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    parts = [
        first("road", "pedestrian", "footway", "residential", "highway"),
        first("neighbourhood", "suburb", "quarter", "city_district"),
        first("city", "town", "village", "county", "state_district"),
    ]
    unique: list[str] = []
    for part in parts:
        if part and part not in unique:
            unique.append(part)
    if unique:
        return ", ".join(unique)[:500]
    display = payload.get("display_name")
    return display.strip()[:500] if isinstance(display, str) and display.strip() else None


class NominatimGeocoder:
    """OpenStreetMap Nominatim, kept to one request per second across all
    API processes with a Redis slot. A caller waits briefly for the slot and
    otherwise gives up (no address) rather than queueing behind others."""

    name = "nominatim"
    SLOT_KEY = "geo:nominatim:slot"

    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        timeout: float,
        redis: Redis | None = None,
        min_interval_ms: int = 1000,
        max_wait_seconds: float = 2.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout = timeout
        self._redis = redis
        self.min_interval_ms = min_interval_ms
        self.max_wait_seconds = max_wait_seconds
        self.transport = transport

    async def _acquire_slot(self) -> bool:
        deadline = time.monotonic() + self.max_wait_seconds
        # Looked up per call: the shared client is replaced when the app restarts.
        redis = self._redis or get_redis()
        while True:
            try:
                if await redis.set(self.SLOT_KEY, "1", px=self.min_interval_ms, nx=True):
                    return True
                wait_ms = await redis.pttl(self.SLOT_KEY)
            except RedisError as exc:
                # Without the shared slot we can't promise the provider its
                # rate limit, so we don't call it.
                logger.warning(
                    "geocoder rate limiter unavailable", extra=log_fields(error=repr(exc))
                )
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(max(wait_ms, 50) / 1000, remaining))

    async def reverse(self, lat: float, lng: float, *, locale: str) -> str | None:
        if not await self._acquire_slot():
            logger.info("geocoder busy; skipping address lookup")
            return None
        params = {
            "format": "jsonv2",
            "lat": f"{lat:.{PRECISION}f}",
            "lon": f"{lng:.{PRECISION}f}",
            "zoom": "18",
            "addressdetails": "1",
            "accept-language": locale,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent},
                transport=self.transport,
            ) as http:
                response = await http.get(f"{self.base_url}/reverse", params=params)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("reverse geocoding failed", extra=log_fields(error=repr(exc)))
            raise GeocoderUnavailable() from exc
        if not isinstance(payload, dict) or "error" in payload:
            return None
        return format_address(payload)


class GeocoderUnavailable(Exception):
    pass


def cache_key(provider: str, lat: float, lng: float, locale: str) -> str:
    return f"geo:reverse:v1:{provider}:{locale}:{lat:.{PRECISION}f}:{lng:.{PRECISION}f}"


async def reverse_address(
    geocoder: Geocoder, redis: Redis, lat: float, lng: float, *, locale: str
) -> str | None:
    """The address for a point, through the Redis cache. Never raises."""
    if geocoder.name == "none":
        return None
    settings = get_settings()
    lat, lng = round(lat, PRECISION), round(lng, PRECISION)
    key = cache_key(geocoder.name, lat, lng, locale)
    cached: str | bytes | None = None
    with contextlib.suppress(RedisError):
        cached = await redis.get(key)
    if cached is not None:
        text = cached.decode() if isinstance(cached, bytes) else cached
        return text or None

    try:
        address = await geocoder.reverse(lat, lng, locale=locale)
        ttl = settings.geocoder_cache_ttl_seconds
    except GeocoderUnavailable:
        address, ttl = None, settings.geocoder_failure_ttl_seconds
    except Exception as exc:  # a provider bug must not break the endpoint
        logger.exception("geocoder raised", extra=log_fields(error=repr(exc)))
        address, ttl = None, settings.geocoder_failure_ttl_seconds
    with contextlib.suppress(RedisError):
        await redis.set(key, address or _MISS, ex=ttl)
    return address


@lru_cache
def _configured() -> Geocoder:
    settings = get_settings()
    if settings.geocoder == "nominatim":
        return NominatimGeocoder(
            base_url=settings.nominatim_url,
            user_agent=settings.geocoder_user_agent,
            timeout=settings.geocoder_timeout_seconds,
        )
    return NoGeocoder()


def get_geocoder() -> Geocoder:
    return _configured()


GeocoderDep = Annotated[Geocoder, Depends(get_geocoder)]
