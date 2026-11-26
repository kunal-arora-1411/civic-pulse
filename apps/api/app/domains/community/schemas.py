from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class SupportState(BaseModel):
    issue_id: uuid.UUID
    support_count: int = Field(description='Citizens who said "I face this too".')
    supported: bool = Field(description="Whether the caller supports (and follows) the issue.")
