from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domains.media.models import MediaPurpose, MediaStatus


class UploadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: MediaPurpose
    content_type: str = Field(
        max_length=100,
        examples=["image/jpeg"],
        description="`image/jpeg`, `image/png` or `image/webp`. Checked against the bytes "
        "on completion; anything else is `422 unsupported_media_type`.",
    )
    size_bytes: int = Field(gt=0, description="Exact size of the file that will be PUT.")
    checksum_sha256: str = Field(
        pattern=r"^[0-9a-fA-F]{64}$", description="Hex SHA-256 of the file."
    )

    @field_validator("content_type", mode="before")
    @classmethod
    def _normalise_type(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("checksum_sha256")
    @classmethod
    def _lower_checksum(cls, value: str) -> str:
        return value.lower()


class UploadCreated(BaseModel):
    upload_id: uuid.UUID
    method: Literal["PUT"] = "PUT"
    url: str = Field(description="Pre-signed URL; PUT the file bytes here.")
    headers: dict[str, str] = Field(
        description="Headers to send with the PUT, exactly as given. They are signed."
    )
    expires_in: int
    max_size_bytes: int


class MediaVariants(BaseModel):
    thumb: str | None = Field(description="Signed GET URL, once processing is done.")
    display: str | None


class MediaAssetOut(BaseModel):
    """Returned when an upload completes."""

    id: uuid.UUID
    status: MediaStatus
    content_type: str
    width: int | None
    height: int | None
    variants: MediaVariants
    captured_at: datetime | None


class MediaOut(BaseModel):
    """Media as embedded in reports and issues."""

    id: uuid.UUID
    status: MediaStatus
    width: int | None
    height: int | None
    thumb_url: str | None
    display_url: str | None
    original_url: str | None = Field(description="Staff only; null for everyone else.")
    captured_at: datetime | None
