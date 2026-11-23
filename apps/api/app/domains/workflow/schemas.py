from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from app.core.pagination import Page
from app.domains.rbac.roles import Role
from app.domains.workflow.statuses import IssueStatus


class TransitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_status: IssueStatus
    to_status: IssueStatus
    allowed_roles: list[Role]
    requires_reason: bool
    system_only: bool


class TransitionPage(Page[TransitionOut]):
    pass
