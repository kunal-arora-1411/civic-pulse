from __future__ import annotations

import uuid
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.i18n import I18nDescription, I18nLabel
from app.core.pagination import Page
from app.domains.categories.models import CATEGORY_CODE_PATTERN, MAX_PHOTOS_PER_REPORT

FIELD_KEY_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"
OPTION_VALUE_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,39}$"
ICON_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
MAX_FIELDS = 20
MAX_OPTIONS = 30

FieldType = Literal["text", "number", "select", "boolean"]


class FieldOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(pattern=OPTION_VALUE_PATTERN)
    label_i18n: I18nLabel


class CategoryField(BaseModel):
    """An extra question the report form asks for this category (FR-023)."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=FIELD_KEY_PATTERN, examples=["road_name"])
    type: FieldType
    required: bool = False
    label_i18n: I18nLabel
    options: list[FieldOption] | None = Field(
        default=None, max_length=MAX_OPTIONS, description="Required for `select`, else omitted."
    )

    @model_validator(mode="after")
    def _check_options(self) -> Self:
        if self.type == "select":
            if not self.options:
                raise ValueError("A select field needs at least one option.")
            values = [o.value for o in self.options]
            if len(values) != len(set(values)):
                raise ValueError("Option values must be unique.")
        elif self.options:
            raise ValueError("Only select fields have options.")
        return self


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_photos: int = Field(default=1, ge=0, le=MAX_PHOTOS_PER_REPORT)
    max_photos: int = Field(default=5, ge=0, le=MAX_PHOTOS_PER_REPORT)

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.max_photos < self.min_photos:
            raise ValueError("max_photos must be at least min_photos.")
        return self


class Dedup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    radius_m: int = Field(default=30, ge=1, le=1000)
    window_days: int = Field(default=30, ge=1, le=365)


def _unique_keys(fields: list[CategoryField] | None) -> None:
    if fields is None:
        return
    keys = [f.key for f in fields]
    if len(keys) != len(set(keys)):
        raise ValueError("Field keys must be unique.")


class CategoryRef(BaseModel):
    """The short form embedded in reports and issues."""

    id: uuid.UUID
    code: str
    name_i18n: dict[str, str]
    icon: str


class CategoryOut(BaseModel):
    id: uuid.UUID
    code: str
    parent_id: uuid.UUID | None
    name_i18n: dict[str, str]
    description_i18n: dict[str, str]
    icon: str = Field(description="A lucide icon name.")
    evidence: Evidence
    fields: list[CategoryField]
    default_department_id: uuid.UUID | None
    dedup: Dedup = Field(description="Stored now; duplicate matching uses it from Phase 2.")
    sort_order: int
    is_active: bool


class CategoryPage(Page[CategoryOut]):
    pass


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=CATEGORY_CODE_PATTERN, examples=["pothole"])
    parent_id: uuid.UUID | None = None
    name_i18n: I18nLabel
    description_i18n: I18nDescription = Field(default_factory=dict)
    icon: str = Field(max_length=64, pattern=ICON_PATTERN, examples=["construction"])
    evidence: Evidence = Field(default_factory=Evidence)
    fields: list[CategoryField] = Field(default_factory=list, max_length=MAX_FIELDS)
    default_department_id: uuid.UUID | None = None
    dedup: Dedup = Field(default_factory=Dedup)
    sort_order: int = Field(default=0, ge=-10_000, le=10_000)
    is_active: bool = True

    @model_validator(mode="after")
    def _check_fields(self) -> Self:
        _unique_keys(self.fields)
        return self


class CategoryUpdate(BaseModel):
    """Partial update. Send only what changes; `parent_id` and
    `default_department_id` can be set to null to clear them."""

    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, pattern=CATEGORY_CODE_PATTERN)
    parent_id: uuid.UUID | None = None
    name_i18n: I18nLabel | None = None
    description_i18n: I18nDescription | None = None
    icon: str | None = Field(default=None, max_length=64, pattern=ICON_PATTERN)
    evidence: Evidence | None = None
    fields: list[CategoryField] | None = Field(default=None, max_length=MAX_FIELDS)
    default_department_id: uuid.UUID | None = None
    dedup: Dedup | None = None
    sort_order: int | None = Field(default=None, ge=-10_000, le=10_000)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        _unique_keys(self.fields)
        nullable = {"parent_id", "default_department_id"}
        for name in self.model_fields_set - nullable:
            if getattr(self, name) is None:
                raise ValueError(f"{name} can't be null.")
        return self


def fields_as_json(fields: list[CategoryField]) -> list[dict[str, Any]]:
    return [f.model_dump(mode="json", exclude_none=True) for f in fields]
