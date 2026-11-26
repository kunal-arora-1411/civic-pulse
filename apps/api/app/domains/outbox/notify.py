"""What every external channel does before it sends a notification.

Each in-app notification also becomes a `notification.created` outbox event
(trigger in migration 0012). For each channel the dispatcher asks: is the
person still there and reachable, do they want this kind here, and have they
just been told the same thing on this channel? Every "no" is a `skipped`
delivery with the reason, so the log shows why a message did not go out
(PRD §15.2: attempts, failures and provider ids are logged).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.notifications import preferences
from app.domains.notifications.render import Rendered, render
from app.domains.outbox.models import OutboxEvent

NOTIFICATION_EVENT = "notification.created"


@dataclass(frozen=True, slots=True)
class Facts:
    """One notification and the person it is for."""

    notification_id: uuid.UUID
    user_id: uuid.UUID
    kind: str
    body_key: str
    params: dict[str, Any]
    link: str | None
    issue_id: uuid.UUID | None
    phone: str | None
    email: str | None
    locale: str
    display_name: str | None

    def rendered(self) -> Rendered:
        return render(
            kind=self.kind,
            body_key=self.body_key,
            params=self.params,
            link=self.link,
            locale=self.locale,
            web_url=get_settings().web_url,
        )


@dataclass(frozen=True, slots=True)
class Loaded:
    facts: Facts | None = None
    skip: str | None = None


async def load(db: AsyncSession, event: OutboxEvent, channel: str) -> Loaded:
    """The notification, its recipient, and whether this channel may carry it."""
    raw = event.payload.get("notification_id")
    try:
        notification_id = uuid.UUID(str(raw))
    except ValueError:
        return Loaded(skip="the event names no notification")
    row = (
        await db.execute(
            text(
                "SELECT n.user_id, n.kind, n.body_key, n.params, n.link, n.issue_id, "
                "       u.phone, u.email, u.locale, u.display_name, u.is_active "
                "FROM notifications n JOIN users u ON u.id = n.user_id "
                "WHERE n.id = :id AND n.tenant_id = :tenant"
            ),
            {"id": notification_id, "tenant": event.tenant_id},
        )
    ).one_or_none()
    if row is None:
        return Loaded(skip="the notification is gone")
    user_id, kind, body_key, params, link, issue_id, phone, email, locale, name, active = row
    if not active:
        return Loaded(skip="the recipient's account is deactivated")
    if not await preferences.enabled(db, user_id, kind, channel):
        return Loaded(skip=f"the recipient turned {kind} off on {channel}")
    facts = Facts(
        notification_id=notification_id,
        user_id=user_id,
        kind=kind,
        body_key=body_key,
        params=params or {},
        link=link,
        issue_id=issue_id,
        phone=phone,
        email=email,
        locale=locale or "en",
        display_name=name,
    )
    if await _duplicate(db, event, facts, channel):
        return Loaded(skip="the same notification went out on this channel moments ago")
    return Loaded(facts=facts)


async def _duplicate(db: AsyncSession, event: OutboxEvent, facts: Facts, channel: str) -> bool:
    """Whether this person was just sent an identical notification here.

    Identical means same kind, issue and parameters (so two different status
    changes are both sent, but a status flipping back and forth, or a
    trigger firing twice, is not).
    """
    since = datetime.now(UTC) - timedelta(minutes=get_settings().notification_dedup_minutes)
    found = await db.scalar(
        text(
            "SELECT 1 FROM outbox_deliveries d "
            "JOIN outbox_events e ON e.id = d.event_id "
            "JOIN notifications n ON n.id = (e.payload->>'notification_id')::uuid "
            "WHERE d.channel = :channel AND d.outcome = 'delivered' "
            "  AND e.event_type = :type AND e.id <> :event "
            "  AND n.user_id = :user AND n.kind = :kind "
            "  AND n.issue_id IS NOT DISTINCT FROM :issue AND n.params = CAST(:params AS jsonb) "
            "  AND d.created_at > :since "
            "LIMIT 1"
        ),
        {
            "channel": channel,
            "type": NOTIFICATION_EVENT,
            "event": event.id,
            "user": facts.user_id,
            "kind": facts.kind,
            "issue": facts.issue_id,
            "params": json.dumps(facts.params),
            "since": since,
        },
    )
    return found is not None


async def sent_today(db: AsyncSession, user_id: uuid.UUID, channel: str) -> int:
    """Notifications delivered to this person on `channel` in the last day."""
    since = datetime.now(UTC) - timedelta(days=1)
    count = await db.scalar(
        text(
            "SELECT count(*) FROM outbox_deliveries d "
            "JOIN outbox_events e ON e.id = d.event_id "
            "WHERE d.channel = :channel AND d.outcome = 'delivered' "
            "  AND e.event_type = :type AND e.payload->>'user_id' = :user "
            "  AND d.created_at > :since"
        ),
        {"channel": channel, "type": NOTIFICATION_EVENT, "user": str(user_id), "since": since},
    )
    return int(count or 0)
