from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.pagination import Page
from app.domains.org.models import DEPARTMENT_CODE_PATTERN, JurisdictionKind


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    is_active: bool
    created_at: datetime


class DepartmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    code: str = Field(
        pattern=DEPARTMENT_CODE_PATTERN,
        examples=["ROADS"],
        description="Uppercase letters, digits and underscores; lowercase input is upper-cased.",
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name must not be blank.")
        return value

    @field_validator("code", mode="before")
    @classmethod
    def _upper_code(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value


class DepartmentPage(Page[DepartmentOut]):
    pass


class JurisdictionOut(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    kind: JurisdictionKind
    name: str
    code: str
    geometry: dict[str, Any] | None = Field(
        default=None,
        description="GeoJSON MultiPolygon. Only present with `include_geometry=true`.",
    )


class JurisdictionPage(Page[JurisdictionOut]):
    pass
