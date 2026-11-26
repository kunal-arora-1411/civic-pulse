"""The outbox's SMS channel: one-time passwords and notification texts.

A sign-in code is an `auth.otp` event written in the same transaction as the
challenge, then delivered straight after the request commits (a job, so the
response does not wait on the provider) with the regular dispatcher as the
fallback. The code is Fernet-encrypted in the payload (TOTP_ENCRYPTION_KEY),
so the outbox never holds a usable code in clear, and a code that expired
before it could be sent is skipped rather than retried.

Notification texts follow the recipient's preferences, are de-duplicated,
and are capped per person per day (`NOTIFICATION_SMS_PER_DAY`): SMS costs
money and is the most intrusive channel.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.phone import mask_phone
from app.core.security import decrypt_secret, encrypt_secret
from app.core.tenancy import system_session
from app.domains.auth.sms import SmsProvider
from app.domains.notifications.render import sms_text
from app.domains.outbox import notify
from app.domains.outbox.channels import Delivery
from app.domains.outbox.models import OutboxEvent

CHANNEL = "sms"
OTP_EVENT = "auth.otp"


def otp_event(
    *,
    tenant_id: uuid.UUID | None,
    challenge_id: uuid.UUID,
    phone: str,
    code: str,
    expires_at: datetime,
) -> OutboxEvent:
    """The outbox row that will text a sign-in code. Add it with the challenge."""
    return OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        event_type=OTP_EVENT,
        aggregate_type="otp_challenge",
        aggregate_id=challenge_id,
        payload={
            "phone": phone,
            "code": encrypt_secret(code),
            "expires_at": expires_at.isoformat(),
        },
    )


class SmsChannel:
    name = CHANNEL

    def __init__(self, provider: SmsProvider) -> None:
        self.provider = provider

    def handles(self, event_type: str) -> bool:
        return event_type in (OTP_EVENT, notify.NOTIFICATION_EVENT)

    async def deliver(self, event: OutboxEvent) -> Delivery:
        if event.event_type == OTP_EVENT:
            return await self._otp(event)
        async with system_session(reason="outbox: sms channel") as db:
            return await self._notification(db, event)

    async def _otp(self, event: OutboxEvent) -> Delivery:
        phone = str(event.payload.get("phone") or "")
        expires_at = datetime.fromisoformat(str(event.payload.get("expires_at")))
        remaining = int((expires_at - datetime.now(UTC)).total_seconds())
        if remaining <= 0:
            return Delivery.skipped(CHANNEL, "the code expired before it could be sent")
        code = decrypt_secret(str(event.payload.get("code")))
        await self.provider.send_otp(phone, code, ttl_seconds=remaining)
        return Delivery(channel=CHANNEL, detail=f"code to {mask_phone(phone)}")

    async def _notification(self, db: AsyncSession, event: OutboxEvent) -> Delivery:
        loaded = await notify.load(db, event, CHANNEL)
        if loaded.facts is None:
            return Delivery.skipped(CHANNEL, loaded.skip or "nothing to send")
        facts = loaded.facts
        if not facts.phone:
            return Delivery.skipped(CHANNEL, "the recipient has no mobile number")
        limit = get_settings().notification_sms_per_day
        if await notify.sent_today(db, facts.user_id, CHANNEL) >= limit:
            return Delivery.skipped(CHANNEL, f"the recipient reached {limit} texts today")
        message_id = await self.provider.send_text(facts.phone, sms_text(facts.rendered()))
        return Delivery(channel=CHANNEL, detail=f"id {message_id}" if message_id else None)
