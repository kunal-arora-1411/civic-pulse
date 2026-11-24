from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core.pagination import Page
from app.domains.notifications.models import NotificationKind


class NotificationOut(BaseModel):
    """`title_key`/`body_key` are message keys under the client's
    `notifications.messages` namespace; `params` fill their placeholders."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: NotificationKind
    title_key: str
    body_key: str
    params: dict[str, Any]
    link: str | None
    issue_id: uuid.UUID | None
    read_at: datetime | None
    created_at: datetime


class NotificationPage(Page[NotificationOut]):
    unread: int


class UnreadCount(BaseModel):
    unread: int


class ReadAllResult(BaseModel):
    updated: int
