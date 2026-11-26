"""Reading and acknowledging the caller's own notifications.

Rows are tenant-scoped by RLS and user-scoped here: nobody, staff included,
reads or marks another person's notifications.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import get_client
from app.core.errors import Forbidden, NotFound, ServiceUnavailable, ValidationFailed
from app.core.pagination import PageParams, paginate
from app.domains.notifications import preferences
from app.domains.notifications.models import (
    Notification,
    NotificationPreference,
    PushSubscription,
)
from app.domains.notifications.schemas import (
    ChannelAvailability,
    ChannelChoice,
    KindPreferences,
    NotificationOut,
    NotificationPage,
    NotificationPreferences,
    PreferencesUpdate,
    PushSubscriptionIn,
    PushSubscriptionOut,
)
from app.domains.rbac.principal import Principal
from app.domains.users.models import User


async def unread_count(db: AsyncSession, principal: Principal) -> int:
    total = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == principal.user_id, Notification.read_at.is_(None))
    )
    return int(total or 0)


async def list_for(
    db: AsyncSession, principal: Principal, page: PageParams, *, unread_only: bool
) -> NotificationPage:
    stmt = select(Notification).where(Notification.user_id == principal.user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
    rows, total = await paginate(db, stmt, page)
    return NotificationPage(
        items=[NotificationOut.model_validate(row[0]) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
        unread=await unread_count(db, principal),
    )


async def mark_read(
    db: AsyncSession, principal: Principal, notification_id: uuid.UUID
) -> NotificationOut:
    row = await db.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == principal.user_id
        )
    )
    if row is None:
        raise NotFound()
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        await db.flush()
    return NotificationOut.model_validate(row)


async def mark_all_read(db: AsyncSession, principal: Principal) -> int:
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == principal.user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    return int(getattr(result, "rowcount", 0) or 0)


# --- delivery preferences and Web Push subscriptions -----------------------------------


def _tenant_of(principal: Principal) -> uuid.UUID:
    # A platform administrator has no tenant, so no inbox and nothing to
    # deliver; these settings exist only inside a municipality.
    if principal.tenant_id is None:
        raise Forbidden("Notification settings belong to a municipality account.")
    return principal.tenant_id


async def get_preferences(db: AsyncSession, principal: Principal) -> NotificationPreferences:
    _tenant_of(principal)
    settings = get_settings()
    user = await db.get(User, principal.user_id)
    choices = await preferences.saved(db, principal.user_id)
    by_kind: dict[str, KindPreferences] = {}
    for kind, channel, on in preferences.effective(preferences.kinds_for(principal), choices):
        entry = by_kind.setdefault(kind.value, KindPreferences(kind=kind, channels=[]))
        entry.channels.append(
            ChannelChoice(channel=channel, enabled=on, default=preferences.default(kind, channel))
        )
    return NotificationPreferences(
        items=list(by_kind.values()),
        available=ChannelAvailability(
            email=settings.mail_enabled and bool(user and user.email),
            sms=bool(user and user.phone),
            push=settings.push_enabled,
        ),
        push_public_key=settings.vapid_public_key.strip() or None,
    )


async def update_preferences(
    db: AsyncSession, principal: Principal, body: PreferencesUpdate
) -> NotificationPreferences:
    tenant_id = _tenant_of(principal)
    offered = set(preferences.kinds_for(principal))
    for item in body.items:
        if item.kind not in offered or not preferences.allowed(item.kind, item.channel):
            raise ValidationFailed(
                f"{item.kind.value} is not sent on {item.channel.value}.",
                details={"kind": item.kind.value, "channel": item.channel.value},
            )
    for item in body.items:
        await db.execute(
            insert(NotificationPreference)
            .values(
                tenant_id=tenant_id,
                user_id=principal.user_id,
                kind=item.kind.value,
                channel=item.channel.value,
                enabled=item.enabled,
            )
            .on_conflict_do_update(
                constraint="pk_notification_preferences",
                set_={"enabled": item.enabled, "updated_at": func.clock_timestamp()},
            )
        )
    return await get_preferences(db, principal)


def _push_host_allowed(endpoint: str) -> bool:
    parsed = urlsplit(endpoint)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return False
    return any(
        host == allowed or host.endswith(f".{allowed}")
        for allowed in get_settings().push_endpoint_hosts
    )


async def subscribe_push(
    db: AsyncSession, principal: Principal, body: PushSubscriptionIn
) -> PushSubscriptionOut:
    tenant_id = _tenant_of(principal)
    if not get_settings().push_enabled:
        raise ServiceUnavailable("Web Push is not configured on this server.")
    if not _push_host_allowed(body.endpoint):
        raise ValidationFailed(
            "The endpoint is not a known browser push service.",
            details={"field": "endpoint"},
        )
    agent = get_client().user_agent
    values = {
        "p256dh": body.keys.p256dh,
        "auth": body.keys.auth,
        "user_agent": agent[:400] if agent else None,
    }
    # One row per browser: a shared device that signs in as someone else
    # moves to that person rather than keeping the previous one's pushes.
    row = await db.scalar(
        insert(PushSubscription)
        .values(tenant_id=tenant_id, user_id=principal.user_id, endpoint=body.endpoint, **values)
        .on_conflict_do_update(
            constraint="uq_push_subscriptions_tenant_endpoint",
            set_={"user_id": principal.user_id, **values},
        )
        .returning(PushSubscription)
    )
    assert row is not None
    return PushSubscriptionOut.model_validate(row)


async def unsubscribe_push(db: AsyncSession, principal: Principal, endpoint: str) -> None:
    """Idempotent; only the caller's own subscription is removed."""
    _tenant_of(principal)
    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.user_id == principal.user_id,
            PushSubscription.endpoint == endpoint,
        )
    )
