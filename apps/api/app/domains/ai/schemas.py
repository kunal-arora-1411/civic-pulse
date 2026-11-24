from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domains.ai.models import ClassificationStatus
from app.domains.categories.models import MAX_PHOTOS_PER_REPORT


class ClassificationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_PHOTOS_PER_REPORT)

    @field_validator("media_ids")
    @classmethod
    def _unique(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Each photo can only be listed once.")
        return value


class Suggestion(BaseModel):
    category_id: uuid.UUID
    code: str
    confidence: float = Field(ge=0, le=1)


class ClassificationOut(BaseModel):
    id: uuid.UUID
    status: ClassificationStatus
    model_id: str | None = Field(examples=["clip-vit-b32@onnx-1"])
    suggestions: list[Suggestion] = Field(
        description="Active categories only, best first, at most 3."
    )
    not_civic: bool = Field(
        description="The photos look like something other than a civic problem. A soft "
        "warning only; the citizen can still report."
    )
    needs_manual: bool = Field(
        description="Too unsure to pre-select: ask the citizen to choose (also true while "
        "pending and when failed)."
    )
    error: str | None = Field(
        description="`ai_unavailable` when the AI couldn't run; the client just asks for "
        "manual selection."
    )
    created_at: datetime


# --- governance (contract G) --------------------------------------------------------------


class ModelOut(BaseModel):
    id: str
    task: str
    name: str
    version: str
    source: str | None
    license: str | None
    deployed_at: datetime
    intended_use: str | None
    metrics: dict[str, object]


class ModelsOut(BaseModel):
    models: list[ModelOut] = Field(description="Newest deployment first.")
    active: dict[str, str | None] = Field(
        description="Per task (`embedding`, `classification`, `face_detection`): the most "
        "recently deployed model, or null."
    )
