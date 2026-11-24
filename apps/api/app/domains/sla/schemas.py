from __future__ import annotations

import uuid
from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.domains.priority.rules import PriorityBand


class SlaTargetIn(BaseModel):
    category_id: uuid.UUID
    priority_band: PriorityBand | None = Field(
        default=None, description="Null: every band without a narrower target."
    )
    resolve_hours: int = Field(ge=1, le=8760, description="Hours from report to resolution.")
    escalate_after_hours: int = Field(
        ge=1,
        le=8760,
        description="Hours after the breach before the municipal admins are told.",
    )


class SlaTargetOut(SlaTargetIn):
    id: uuid.UUID


class SlaTargets(BaseModel):
    items: list[SlaTargetOut]


class SlaTargetsUpdate(BaseModel):
    items: list[SlaTargetIn] = Field(max_length=500)

    @model_validator(mode="after")
    def _unique(self) -> Self:
        seen: set[tuple[uuid.UUID, PriorityBand | None]] = set()
        for item in self.items:
            key = (item.category_id, item.priority_band)
            if key in seen:
                raise ValueError("Each category and band may have only one target.")
            seen.add(key)
        return self
