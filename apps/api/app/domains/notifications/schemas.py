from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.pagination import Page
from app.domains.notifications.models import DeliveryChannel, NotificationKind


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


class ChannelChoice(BaseModel):
    channel: DeliveryChannel
    enabled: bool
    default: bool


class KindPreferences(BaseModel):
    kind: NotificationKind
    channels: list[ChannelChoice]


class ChannelAvailability(BaseModel):
    """Whether a channel can reach this person at all right now: a relay
    and an email address; a mobile number; a configured push service."""

    email: bool
    sms: bool
    push: bool


class NotificationPreferences(BaseModel):
    """Only the kinds this person can receive, each with the channels the
    PRD allows for it. The in-app inbox always gets everything."""

    items: list[KindPreferences]
    available: ChannelAvailability
    # The VAPID public key a browser subscribes with; null when Web Push is off.
    push_public_key: str | None


class PreferenceChange(BaseModel):
    kind: NotificationKind
    channel: DeliveryChannel
    enabled: bool


class PreferencesUpdate(BaseModel):
    """Only the listed choices change; the rest keep their current value."""

    items: list[PreferenceChange] = Field(min_length=1, max_length=50)


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class PushSubscriptionIn(BaseModel):
    """`PushSubscription.toJSON()` from the browser, as is."""

    endpoint: str = Field(min_length=1, max_length=1000)
    keys: PushKeys


class PushSubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    endpoint: str
    created_at: datetime
