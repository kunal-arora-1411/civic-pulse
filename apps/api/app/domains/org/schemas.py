from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.pagination import Page
from app.domains.org.models import DEPARTMENT_CODE_PATTERN, JurisdictionKind, TeamRole


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


# --- Teams (Phase 3, FR-061) -------------------------------------------------------------

_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class ScheduleDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekday: int = Field(ge=0, le=6, description="0 = Monday.")
    start: str = Field(pattern=_HHMM, examples=["09:00"])
    end: str = Field(pattern=_HHMM, examples=["18:00"])

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start >= self.end:
            raise ValueError("`start` must be before `end`.")
        return self


class Schedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(default="Asia/Kolkata", max_length=64)
    days: list[ScheduleDay] = Field(max_length=7)

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown time zone.") from exc
        return value

    @field_validator("days")
    @classmethod
    def _one_per_day(cls, value: list[ScheduleDay]) -> list[ScheduleDay]:
        if len({d.weekday for d in value}) != len(value):
            raise ValueError("At most one entry per weekday.")
        return value


class TeamMemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    team_role: TeamRole = TeamRole.MEMBER


class UserRef(BaseModel):
    id: uuid.UUID
    display_name: str | None


class TeamMemberOut(BaseModel):
    user: UserRef
    team_role: TeamRole


class DepartmentRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class TeamOut(BaseModel):
    id: uuid.UUID
    department: DepartmentRef
    name: str
    is_active: bool
    members: list[TeamMemberOut]
    jurisdiction_ids: list[uuid.UUID]
    category_ids: list[uuid.UUID]
    schedule: Schedule | None
    created_at: datetime
    updated_at: datetime


class TeamPage(Page[TeamOut]):
    pass


def _unique_members(value: list[TeamMemberIn] | None) -> list[TeamMemberIn] | None:
    if value is not None and len({m.user_id for m in value}) != len(value):
        raise ValueError("Each user can only be listed once.")
    return value


def _unique_ids(value: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
    if value is not None and len(set(value)) != len(value):
        raise ValueError("Each id can only be listed once.")
    return value


def _strip_required(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("Name must not be blank.")
    return value


class TeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    members: list[TeamMemberIn] = Field(default_factory=list, max_length=200)
    jurisdiction_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    category_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    schedule: Schedule | None = None

    _name = field_validator("name")(_strip_required)
    _members = field_validator("members")(_unique_members)
    _ids = field_validator("jurisdiction_ids", "category_ids")(_unique_ids)


class TeamUpdate(BaseModel):
    """Partial update. Lists replace what is stored; `schedule` can be null."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None
    members: list[TeamMemberIn] | None = Field(default=None, max_length=200)
    jurisdiction_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)
    category_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)
    schedule: Schedule | None = None

    _name = field_validator("name")(_strip_required)
    _members = field_validator("members")(_unique_members)
    _ids = field_validator("jurisdiction_ids", "category_ids")(_unique_ids)

    @model_validator(mode="after")
    def _not_null(self) -> Self:
        for name in self.model_fields_set - {"schedule"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} can't be null.")
        return self


class TeamRef(BaseModel):
    id: uuid.UUID
    name: str


class EligibleTeam(BaseModel):
    team: TeamRef
    department: DepartmentRef
    members: list[TeamMemberOut]
