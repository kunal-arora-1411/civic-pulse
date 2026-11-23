from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.core.pagination import Page


class AuditActor(BaseModel):
    id: uuid.UUID
    display_name: str | None


class AuditEventOut(BaseModel):
    id: int
    occurred_at: datetime
    actor: AuditActor | None
    action: str
    entity_type: str
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    request_id: str | None


class AuditEventPage(Page[AuditEventOut]):
    pass
