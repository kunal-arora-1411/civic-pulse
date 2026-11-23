from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.phone import PhoneNumber
from app.domains.users.schemas import UserMe

OtpCode = Field(min_length=4, max_length=10, pattern=r"^\d+$", examples=["123456"])


class OtpRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: PhoneNumber


class OtpRequestOut(BaseModel):
    challenge_id: uuid.UUID
    expires_in: int = Field(description="Seconds until the code expires.")
    resend_after: int = Field(description="Seconds before another code can be requested.")


class OtpVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: uuid.UUID
    code: str = OtpCode


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 (not a secret)
    expires_in: int
    refresh_token: str
    user: UserMe


class MfaChallengeResponse(BaseModel):
    mfa_required: Literal[True] = True
    mfa_token: str


class MfaVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mfa_token: str = Field(max_length=2048)
    code: str = Field(min_length=6, max_length=8, pattern=r"^\d+$")


class RefreshIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str | None = Field(default=None, max_length=256)


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class MfaEnableIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=6, max_length=8, pattern=r"^\d+$")
