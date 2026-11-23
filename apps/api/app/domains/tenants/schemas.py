from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.pagination import Page
from app.domains.tenants.models import SLUG_PATTERN


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    default_locale: str
    supported_locales: list[str]


class MapConfig(BaseModel):
    """Initial map view. Coordinates are `[lng, lat]`, in GeoJSON order."""

    center: tuple[float, float] = Field(examples=[[77.5946, 12.9716]])
    zoom: int = Field(ge=0, le=22, examples=[12])
    bounds: tuple[float, float, float, float] = Field(
        description="`[min_lng, min_lat, max_lng, max_lat]` of the city boundary.",
        examples=[[77.50, 12.90, 77.70, 13.05]],
    )


class TenantCurrent(TenantOut):
    map: MapConfig | None = Field(
        description="From the city jurisdiction's geometry; null if the tenant has none yet."
    )


class PlatformTenant(TenantOut):
    is_active: bool
    created_at: datetime


class PlatformTenantPage(Page[PlatformTenant]):
    pass


class TenantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=63, pattern=SLUG_PATTERN, examples=["demo-city"])
    name: str = Field(min_length=1, max_length=200)

    @field_validator("slug", mode="before")
    @classmethod
    def _lower_slug(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name must not be blank.")
        return value
