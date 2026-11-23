from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    default_locale: str
    supported_locales: list[str]
