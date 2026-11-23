"""Application settings, loaded from the environment (and `.env` files).

Secrets have no defaults on purpose: a missing secret should fail at startup,
not silently fall back to something guessable. Development values live in the
repo-root `.env.example` and in `infra/docker-compose.yml`.
"""

from __future__ import annotations

import base64
import binascii
import json
from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # apps/api/.env first, then the repo-root .env when run from apps/api.
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    service_name: str = "civicpulse-api"

    # The API connects as the non-superuser app role so that RLS applies.
    # Migrations use the owner role and are the only thing that needs it.
    database_url: str
    migration_database_url: str | None = None
    db_pool_size: int = 10
    db_max_overflow: int = 10

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None

    # Comma-separated in the environment: CORS_ORIGINS=http://a,http://b
    # (3100 is the web app's alternate dev port.)
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:3100",
    ]

    # Tokens
    jwt_secret: SecretStr
    jwt_issuer: str = "civicpulse"
    jwt_audience: str = "civicpulse-api"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 30 * 24 * 3600
    # A refresh token presented again within this many seconds of being
    # rotated is treated as a benign race (two tabs refreshing at once)
    # rather than as theft. See docs/adr/0003.
    refresh_reuse_grace_seconds: int = 10
    mfa_token_ttl_seconds: int = 300
    cookie_secure: bool | None = None

    # OTP
    otp_hmac_secret: SecretStr
    otp_length: int = 6
    otp_ttl_seconds: int = 300
    otp_resend_seconds: int = 30
    otp_max_attempts: int = 5
    otp_max_per_hour: int = 5
    otp_max_per_ip_per_hour: int = 30
    dev_fixed_otp: bool = False
    dev_fixed_otp_code: str = "000000"
    sms_provider: str = "console"

    # MFA
    totp_encryption_key: SecretStr
    totp_issuer: str = "CivicPulse"
    totp_max_attempts: int = 5
    require_staff_mfa: bool | None = None

    idempotency_ttl_seconds: int = 24 * 3600

    # Object storage (S3 API; MinIO in development). The API talks to
    # S3_ENDPOINT, which may be an internal hostname. Pre-signed URLs are
    # handed to browsers, and a SigV4 signature covers the Host header, so
    # they must be signed for the address the browser will use:
    # S3_PUBLIC_ENDPOINT. The two only differ when storage sits on a private
    # network (docker compose, a VPC endpoint).
    s3_endpoint: str = "http://localhost:9000"
    s3_public_endpoint: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_bucket: str = "civicpulse-media"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("["):
                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("totp_encryption_key")
    @classmethod
    def _check_fernet_key(cls, value: SecretStr) -> SecretStr:
        try:
            raw = base64.urlsafe_b64decode(value.get_secret_value().encode())
        except (binascii.Error, ValueError) as exc:
            raise ValueError("TOTP_ENCRYPTION_KEY must be a urlsafe base64 Fernet key") from exc
        if len(raw) != 32:
            raise ValueError("TOTP_ENCRYPTION_KEY must decode to 32 bytes")
        return value

    @model_validator(mode="after")
    def _check_production(self) -> Settings:
        if self.env is Environment.PRODUCTION:
            for name in ("jwt_secret", "otp_hmac_secret"):
                secret: SecretStr = getattr(self, name)
                if len(secret.get_secret_value()) < 32:
                    raise ValueError(f"{name.upper()} must be at least 32 characters in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.env is Environment.PRODUCTION

    @property
    def fixed_otp_enabled(self) -> bool:
        # The fixed code is a development convenience and is never honoured
        # in production, whatever DEV_FIXED_OTP says.
        return self.dev_fixed_otp and not self.is_production

    @property
    def staff_mfa_required(self) -> bool:
        if self.require_staff_mfa is None:
            return self.is_production
        return self.require_staff_mfa

    @property
    def refresh_cookie_secure(self) -> bool:
        if self.cookie_secure is None:
            return self.is_production
        return self.cookie_secure

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def s3_presign_endpoint(self) -> str:
        return self.s3_public_endpoint or self.s3_endpoint


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]
