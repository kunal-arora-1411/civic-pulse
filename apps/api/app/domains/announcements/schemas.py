from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from app.core.i18n import I18nBody, I18nLabel
from app.core.pagination import Page
from app.domains.analytics.schemas import WardRef
from app.domains.announcements.models import AnnouncementKind
from app.domains.categories.schemas import CategoryRef
from app.domains.org.schemas import UserRef

AnnouncementState = Literal["scheduled", "active", "ended", "withdrawn"]


class AnnouncementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: AnnouncementKind
    title_i18n: I18nLabel
    body_i18n: I18nBody
    ward_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def _check_period(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("`ends_at` must be after `starts_at`.")
        return self


class AnnouncementUpdate(BaseModel):
    """Only the fields sent change. `ward_id`/`category_id` sent as null
    widen the notice to the whole city / every category."""

    model_config = ConfigDict(extra="forbid")

    kind: AnnouncementKind | None = None
    title_i18n: I18nLabel | None = None
    body_i18n: I18nBody | None = None
    ward_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None


class AnnouncementOut(BaseModel):
    id: uuid.UUID
    kind: AnnouncementKind
    title_i18n: dict[str, str]
    body_i18n: dict[str, str]
    ward: WardRef | None
    category: CategoryRef | None
    starts_at: datetime
    ends_at: datetime
    state: AnnouncementState
    withdrawn_at: datetime | None
    created_by: UserRef | None
    created_at: datetime
    updated_at: datetime


AnnouncementPage = Page[AnnouncementOut]


class PublicAnnouncement(BaseModel):
    id: uuid.UUID
    kind: AnnouncementKind
    title_i18n: dict[str, str]
    body_i18n: dict[str, str]
    ward: WardRef | None
    category: CategoryRef | None
    starts_at: datetime
    ends_at: datetime
