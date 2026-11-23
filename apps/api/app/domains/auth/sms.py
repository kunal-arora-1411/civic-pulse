"""SMS delivery behind a small interface, so providers can be swapped later."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings
from app.core.logging import log_fields
from app.core.phone import mask_phone

logger = logging.getLogger("civicpulse.sms")


class SmsProvider(Protocol):
    async def send_otp(self, phone: str, code: str, *, ttl_seconds: int) -> None: ...


class ConsoleSmsProvider:
    """Development provider: writes the code to the API log instead of sending it."""

    async def send_otp(self, phone: str, code: str, *, ttl_seconds: int) -> None:
        logger.info(
            "OTP for %s: %s (valid %ss)",
            mask_phone(phone),
            code,
            ttl_seconds,
            extra=log_fields(sms_provider="console", phone=mask_phone(phone)),
        )


@lru_cache
def get_sms_provider() -> SmsProvider:
    name = get_settings().sms_provider
    if name == "console":
        return ConsoleSmsProvider()
    raise RuntimeError(f"Unknown SMS_PROVIDER {name!r}")
