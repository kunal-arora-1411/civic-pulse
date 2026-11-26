"""SMS delivery behind a small interface, so providers can be swapped later.

Nothing here is called from a request any more: one-time passwords and
notification texts both go through the outbox (`app/domains/outbox/sms.py`),
so a slow or failing provider costs a retry, not a sign-in.

No provider is chosen yet (MSG91 and Gupshup are the candidates; both need
DLT-registered templates in India). Adding one is a class with these two
methods and a branch in `get_sms_provider`.
"""

from __future__ import annotations

import logging
import uuid
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings
from app.core.logging import log_fields
from app.core.phone import mask_phone

logger = logging.getLogger("civicpulse.sms")


class SmsProvider(Protocol):
    async def send_otp(self, phone: str, code: str, *, ttl_seconds: int) -> None: ...

    async def send_text(self, phone: str, text: str) -> str | None:
        """Send one message; return the provider's message id if it gives one."""
        ...


class ConsoleSmsProvider:
    """Development provider: writes the message to the log instead of sending it."""

    async def send_otp(self, phone: str, code: str, *, ttl_seconds: int) -> None:
        logger.info(
            "OTP for %s: %s (valid %ss)",
            mask_phone(phone),
            code,
            ttl_seconds,
            extra=log_fields(sms_provider="console", phone=mask_phone(phone)),
        )

    async def send_text(self, phone: str, text: str) -> str | None:
        message_id = f"console-{uuid.uuid4()}"
        logger.info(
            "SMS to %s: %s",
            mask_phone(phone),
            text,
            extra=log_fields(
                sms_provider="console", phone=mask_phone(phone), message_id=message_id
            ),
        )
        return message_id


@lru_cache
def get_sms_provider() -> SmsProvider:
    name = get_settings().sms_provider
    if name == "console":
        return ConsoleSmsProvider()
    raise RuntimeError(f"Unknown SMS_PROVIDER {name!r}")
