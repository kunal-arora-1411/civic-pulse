from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from redis.asyncio import Redis

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.redis import get_redis
from app.domains.auth.dependencies import RequestTenantId
from app.domains.geo import service
from app.domains.geo.geocoder import GeocoderDep, reverse_address
from app.domains.tenants.models import Tenant

router = APIRouter(prefix="/geo", tags=["geo"])


class WardRef(BaseModel):
    id: uuid.UUID
    name: str
    code: str


class ZoneRef(BaseModel):
    id: uuid.UUID
    name: str


class ReverseGeocodeOut(BaseModel):
    address_text: str | None
    in_jurisdiction: bool
    ward: WardRef | None
    zone: ZoneRef | None


@router.get(
    "/reverse",
    operation_id="geo_reverse",
    response_model=ReverseGeocodeOut,
    responses=error_responses(401, 403, 404, 422),
)
async def reverse(
    tenant_id: RequestTenantId,
    db: DbSession,
    geocoder: GeocoderDep,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
) -> ReverseGeocodeOut:
    """Address text (when a geocoder is configured) plus ward and zone from
    the municipality's own boundaries. Always 200; `address_text` is null
    when the geocoder is off or failing."""
    placement = await service.place(db, lng, lat)
    tenant = await db.get(Tenant, tenant_id)
    locale = tenant.default_locale if tenant is not None else "en"
    redis: Redis = get_redis()
    address = await reverse_address(geocoder, redis, lat, lng, locale=locale)
    return ReverseGeocodeOut(
        address_text=address,
        in_jurisdiction=placement.in_jurisdiction,
        ward=WardRef(id=placement.ward.id, name=placement.ward.name, code=placement.ward.code)
        if placement.ward
        else None,
        zone=ZoneRef(id=placement.zone.id, name=placement.zone.name) if placement.zone else None,
    )
