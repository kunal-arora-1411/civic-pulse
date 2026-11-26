"""The outbox's Web Push channel (VAPID, RFC 8030/8291/8292).

Each browser a person allowed is a `push_subscriptions` row. A notification
goes to every one of them; a push service that answers 404 or 410 has
dropped the subscription, so the row is deleted rather than retried. The
payload is the same lock-screen-safe title and body as the other channels,
plus the link the service worker opens on click.

Off unless both VAPID keys are set. `pywebpush` is synchronous (requests),
so a send runs in a worker thread with a timeout, as the SMTP mailer does:
the dispatcher holds a transaction open while channels run.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import log_fields
from app.core.tenancy import system_session
from app.domains.notifications.models import PushSubscription
from app.domains.outbox import notify
from app.domains.outbox.channels import Delivery
from app.domains.outbox.models import OutboxEvent

logger = logging.getLogger(__name__)

CHANNEL = "push"
TIMEOUT_SECONDS = 10.0
# How long a push service keeps a message for a browser that is offline.
TTL_SECONDS = 24 * 3600


@dataclass(frozen=True, slots=True)
class Target:
    endpoint: str
    p256dh: str
    auth: str


@dataclass(frozen=True, slots=True)
class PushResult:
    status: int
    message_id: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def gone(self) -> bool:
        # The push service no longer knows this browser.
        return self.status in (404, 410)


class PushSender(Protocol):
    async def send(self, target: Target, payload: str) -> PushResult: ...


class WebPushSender:
    """Encrypts and posts one message with pywebpush."""

    def __init__(self, private_key: str, subject: str) -> None:
        self.private_key = private_key
        self.subject = subject

    async def send(self, target: Target, payload: str) -> PushResult:
        return await asyncio.to_thread(self._send, target, payload)

    def _send(self, target: Target, payload: str) -> PushResult:
        from pywebpush import WebPushException, webpush

        try:
            response = webpush(
                subscription_info={
                    "endpoint": target.endpoint,
                    "keys": {"p256dh": target.p256dh, "auth": target.auth},
                },
                data=payload,
                vapid_private_key=self.private_key,
                vapid_claims={"sub": self.subject},
                timeout=TIMEOUT_SECONDS,
                ttl=TTL_SECONDS,
            )
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else 0
            return PushResult(status=status, error=str(exc)[:200])
        status = getattr(response, "status_code", 201)
        location = getattr(response, "headers", {}).get("Location")
        return PushResult(status=status, message_id=location)


def default_sender() -> PushSender | None:
    settings = get_settings()
    if not settings.push_enabled or settings.vapid_private_key is None:
        return None
    return WebPushSender(settings.vapid_private_key.get_secret_value(), settings.vapid_subject)


class PushChannel:
    name = CHANNEL

    def __init__(self, sender: PushSender) -> None:
        self.sender = sender

    def handles(self, event_type: str) -> bool:
        return event_type == notify.NOTIFICATION_EVENT

    async def deliver(self, event: OutboxEvent) -> Delivery:
        async with system_session(reason="outbox: push channel") as db:
            return await self._deliver(db, event)

    async def _deliver(self, db: AsyncSession, event: OutboxEvent) -> Delivery:
        loaded = await notify.load(db, event, CHANNEL)
        if loaded.facts is None:
            return Delivery.skipped(CHANNEL, loaded.skip or "nothing to send")
        facts = loaded.facts
        subscriptions = (
            await db.scalars(
                select(PushSubscription).where(
                    PushSubscription.user_id == facts.user_id,
                    PushSubscription.tenant_id == event.tenant_id,
                )
            )
        ).all()
        if not subscriptions:
            return Delivery.skipped(CHANNEL, "no browser is subscribed")

        rendered = facts.rendered()
        payload = json.dumps(
            {
                "title": rendered.title,
                "body": rendered.body,
                "url": rendered.url,
                # Same tag replaces rather than stacks a repeat on the device.
                "tag": f"cp-{facts.notification_id}",
            },
            ensure_ascii=False,
        )
        delivered: list[str] = []
        gone: list[uuid.UUID] = []
        errors: list[str] = []
        for sub in subscriptions:
            result = await self.sender.send(Target(sub.endpoint, sub.p256dh, sub.auth), payload)
            if result.ok:
                delivered.append(result.message_id or "")
                await db.execute(
                    update(PushSubscription)
                    .where(PushSubscription.id == sub.id)
                    .values(last_success_at=datetime.now(UTC))
                )
            elif result.gone:
                gone.append(sub.id)
            else:
                errors.append(f"{result.status} {result.error or ''}".strip())
        if gone:
            await db.execute(delete(PushSubscription).where(PushSubscription.id.in_(gone)))
            logger.info(
                "removed expired push subscriptions",
                extra=log_fields(user_id=str(facts.user_id), count=len(gone)),
            )

        if delivered:
            ids = ", ".join(m for m in delivered if m)
            detail = f"{len(delivered)} of {len(subscriptions)} browsers"
            return Delivery(channel=CHANNEL, detail=f"{detail}; {ids}"[:300] if ids else detail)
        if errors:
            # Retried with backoff; an expired subscription is already gone.
            return Delivery.failed(CHANNEL, "; ".join(errors))
        return Delivery.skipped(CHANNEL, "every subscription had expired")
