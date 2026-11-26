from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.pagination import Page


class DeliveryAttempt(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel: str
    outcome: str
    detail: str | None
    created_at: datetime


class DeadLetter(BaseModel):
    """An event the dispatcher gave up on. The payload is not shown: it can
    hold contact details and, for sign-in codes, an encrypted code."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    attempts: int
    last_error: str | None
    created_at: datetime
    dead_lettered_at: datetime | None
    deliveries: list[DeliveryAttempt]


class DeadLetterPage(Page[DeadLetter]):
    pass
